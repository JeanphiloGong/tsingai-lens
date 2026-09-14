from __future__ import annotations

import json
import logging
from asyncio import Semaphore, gather, to_thread
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Callable, Mapping, Sequence

from application.core.objectives.analysis.diagnostics import record_analysis_failure
from application.core.objectives.analysis.evidence_materialization import (
    OBJECTIVE_EVIDENCE_MATERIALIZATION_VERSION,
    materialize_evidence,
    rebind_persisted_contribution,
    rebind_persisted_evidence,
)
from application.core.objectives.analysis.evidence_routing import (
    OBJECTIVE_EVIDENCE_ROUTING_VERSION,
    route_sources,
)
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from application.core.objectives.analysis.paper_experiment import (
    PAPER_EXPERIMENT_RECONSTRUCTION_VERSION,
    assemble_paper_experiments,
    reconstruct_paper_experiments,
)
from application.core.objectives.analysis.source_extraction import (
    OBJECTIVE_SOURCE_EXTRACTION_PROMPT_VERSION,
    ObjectiveSourceExtractor,
    SourceReadAudit,
    extract_and_validate_source_facts,
)
from application.core.objectives.analysis.source_screening import (
    OBJECTIVE_PAPER_FRAME_PROMPT_VERSION,
    ObjectiveSourceScreener,
    screen_sources,
)
from application.core.objectives.analysis.source_validation import (
    OBJECTIVE_SOURCE_GROUNDING_VERSION,
)
from application.core.objectives.analysis_errors import analysis_error_message
from application.core.objectives.objective_input_service import (
    ObjectiveInputService,
    ObjectiveSourceInputs,
    ResearchObjectivesNotReadyError,
)
from application.core.objectives.scope_screening import (
    ObjectiveScopePreview,
    screen_objective_scope,
)
from application.core.paper_facts.extraction import PaperFactsExtractor
from application.repositories.objective_repository import ObjectiveRepository
from application.repositories.paper_map_repository import PaperMapRepository
from application.source.collection_service import CollectionService
from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveDocumentEvidence,
    ObjectiveEvidence,
    PaperContribution,
    PaperExperiment,
    PaperResearchMap,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.source import (
    SourceBlock,
    SourceFigure,
    SourceTable,
    render_markdown_table,
    render_plain_table_text,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


class ObjectiveAnalysisInputs(ObjectiveSourceInputs):
    """The selected prepared Sources plus their Paper Map navigation priors."""

    paper_maps: tuple[PaperResearchMap, ...]


_OBJECTIVE_DOCUMENT_EVIDENCE_VERSION = "objective-document-evidence.v1"
OBJECTIVE_DOCUMENT_EVIDENCE_SCIENTIFIC_VERSIONS = (
    ("paper_framing", OBJECTIVE_PAPER_FRAME_PROMPT_VERSION),
    ("evidence_routing", OBJECTIVE_EVIDENCE_ROUTING_VERSION),
    ("source_extraction", OBJECTIVE_SOURCE_EXTRACTION_PROMPT_VERSION),
    ("source_grounding", OBJECTIVE_SOURCE_GROUNDING_VERSION),
    ("paper_experiment", PAPER_EXPERIMENT_RECONSTRUCTION_VERSION),
    ("evidence_materialization", OBJECTIVE_EVIDENCE_MATERIALIZATION_VERSION),
)
_OBJECTIVE_DOCUMENT_MAX_CONCURRENCY = 4
# Paper reconstruction needs title/abstract/materials context, not a second
# copy of the entire document.  Keep this bounded so context recovery cannot
# inflate every result's lineage or analysis prompt.
_OBJECTIVE_DOCUMENT_CONTEXT_LIMIT = 96
@dataclass(frozen=True)
class ObjectiveAnalysisArtifacts:
    """Canonical values produced by one versioned Objective analysis run."""

    contributions: tuple[PaperContribution, ...]
    evidence_records: tuple[ObjectiveEvidence, ...]
    findings: tuple[Finding, ...]
    model_name: str | None = None
    experiments: tuple[PaperExperiment, ...] = ()


@dataclass(frozen=True)
class ObjectiveDocumentEvidenceArtifacts:
    """Scientific inspection result for one Objective and one document."""

    contribution: PaperContribution
    evidence_records: tuple[ObjectiveEvidence, ...]
    experiments: tuple[PaperExperiment, ...] = ()


class ResearchObjectiveNotFoundError(FileNotFoundError):
    """Raised when one persisted research objective cannot be found."""

    def __init__(self, collection_id: str, objective_id: str) -> None:
        self.collection_id = collection_id
        self.objective_id = objective_id
        super().__init__(f"research objective not found: {collection_id}/{objective_id}")


class ObjectiveScopeNotReadyError(RuntimeError):
    """Raised when no collection Paper Maps are available for scope screening."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(f"objective paper scope not ready: {collection_id}")


class ObjectiveEvidenceAnalysisService:
    """Generate source-grounded artifacts for one confirmed Objective."""

    def __init__(
        self,
        collection_service: CollectionService,
        paper_map_repository: PaperMapRepository,
        objective_repository: ObjectiveRepository,
        finding_synthesis_service: FindingSynthesisService,
        objective_input_service: ObjectiveInputService,
        objective_source_screener: ObjectiveSourceScreener | None = None,
        objective_source_extractor: ObjectiveSourceExtractor | None = None,
        paper_facts_extractor: PaperFactsExtractor | None = None,
    ) -> None:
        self.collection_service = collection_service
        self._objective_source_screener = objective_source_screener
        self._objective_source_extractor = objective_source_extractor
        self._paper_facts_extractor = paper_facts_extractor
        self.paper_map_repository = paper_map_repository
        self.objective_repository = objective_repository
        self.finding_synthesis_service = finding_synthesis_service
        self.objective_input_service = objective_input_service

    async def preview_objective_scope(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveScopePreview:
        """Screen every current collection Paper Map for one persisted Objective."""

        await self.collection_service.get_collection(collection_id)
        objective = await self.objective_repository.read_objective(
            collection_id,
            objective_id,
        )
        if objective is None:
            raise ResearchObjectiveNotFoundError(collection_id, objective_id)
        paper_maps = await self.paper_map_repository.list_collection(collection_id)
        if not paper_maps:
            raise ObjectiveScopeNotReadyError(collection_id)
        return screen_objective_scope(paper_maps, objective=objective)

    async def generate_objective_analysis_artifacts(
        self,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        progress_callback: ProgressCallback | None = None,
    ) -> ObjectiveAnalysisArtifacts:
        if analysis.collection_id != collection_id:
            raise ValueError("analysis belongs to another collection")
        active_objective = await self.objective_repository.read_objective(
            collection_id, analysis.objective_id
        )
        if active_objective is None:
            raise ResearchObjectiveNotFoundError(collection_id, analysis.objective_id)
        if active_objective.active_analysis_version != analysis.analysis_version:
            raise ValueError("analysis is not the active objective version")
        objective_inputs = await self._build_objective_analysis_inputs(
            collection_id,
            document_inputs=analysis.document_inputs,
        )
        response_client = self.objective_input_service.response_client
        if self._objective_source_screener is None:
            self._objective_source_screener = ObjectiveSourceScreener(response_client)
        if self._objective_source_extractor is None:
            self._objective_source_extractor = ObjectiveSourceExtractor(response_client)
        model_name = str(
            getattr(response_client, "model", None) or analysis.model_name or ""
        ).strip()
        if not model_name:
            raise ValueError("Objective document Evidence requires model identity")

        extraction_limit = Semaphore(_OBJECTIVE_DOCUMENT_MAX_CONCURRENCY)
        document_count = len(analysis.document_inputs)
        completed_document_count = 0

        async def report_document_completed(document_id: str) -> None:
            nonlocal completed_document_count
            completed_document_count += 1
            if progress_callback is not None:
                await to_thread(
                    progress_callback,
                    {
                        "phase": "objective_document_evidence_completed",
                        "unit": "documents",
                        "current": completed_document_count,
                        "total": document_count,
                        "active_document_id": document_id,
                        "message": "Finished inspecting one selected paper.",
                    },
                )

        async def inspect_document(
            document_input: PreparedDocumentInput,
        ) -> ObjectiveDocumentEvidenceArtifacts:
            input_fingerprint = self._document_evidence_input_fingerprint(
                objective=active_objective,
                document_input=document_input,
                model_name=model_name,
                extraction_version=_OBJECTIVE_DOCUMENT_EVIDENCE_VERSION,
            )
            checkpoint = await self.objective_repository.read_document_evidence(
                collection_id,
                active_objective.objective_id,
                document_input.document_id,
                input_fingerprint,
            )
            if checkpoint is not None and checkpoint.status == "succeeded":
                artifacts = self._rebind_document_evidence(
                    checkpoint,
                    analysis,
                    objective=active_objective,
                    objective_inputs=objective_inputs,
                )
                await report_document_completed(document_input.document_id)
                return artifacts

            running = ObjectiveDocumentEvidence.start(
                collection_id=collection_id,
                objective_id=active_objective.objective_id,
                document_id=document_input.document_id,
                input_fingerprint=input_fingerprint,
                analysis_version=analysis.analysis_version,
                extraction_version=_OBJECTIVE_DOCUMENT_EVIDENCE_VERSION,
                model_name=model_name,
                started_at=datetime.now(timezone.utc),
            )
            await self.objective_repository.write_document_evidence(running)
            document_objective_inputs = self._objective_inputs_for_document(
                collection_id,
                objective_inputs,
                document_input.document_id,
            )

            document_progress_callback: ProgressCallback | None = None
            if progress_callback is not None:

                def document_progress_callback(detail: dict[str, Any]) -> None:
                    progress_callback(
                        {
                            **detail,
                            "current": completed_document_count,
                            "total": document_count,
                            "active_document_id": document_input.document_id,
                        }
                    )

            try:
                async with extraction_limit:
                    artifacts = await to_thread(
                        self._generate_document_evidence,
                        collection_id=collection_id,
                        analysis=analysis,
                        objective=active_objective,
                        objective_inputs=document_objective_inputs,
                        progress_callback=document_progress_callback,
                    )
                checkpoint = running.succeed(
                    contribution=artifacts.contribution,
                    evidence_records=artifacts.evidence_records,
                    completed_at=datetime.now(timezone.utc),
                )
            except Exception as exc:  # noqa: BLE001
                record_analysis_failure(
                    exc,
                    collection_id=collection_id,
                    objective_id=active_objective.objective_id,
                    document_id=document_input.document_id,
                    stage="document_evidence_extraction",
                )
                logger.error(
                    "Objective document Evidence extraction failed "
                    "collection_id=%s objective_id=%s document_id=%s error_type=%s",
                    collection_id,
                    active_objective.objective_id,
                    document_input.document_id,
                    type(exc).__name__,
                )
                checkpoint = running.fail(
                    contribution=self._failed_document_contribution(
                        collection_id=collection_id,
                        objective_id=active_objective.objective_id,
                        analysis_version=analysis.analysis_version,
                        document_id=document_input.document_id,
                    ),
                    error_code="document_evidence_extraction_failed",
                    error_message=analysis_error_message(
                        "document_evidence_extraction_failed"
                    ),
                    completed_at=datetime.now(timezone.utc),
                )
            await self.objective_repository.write_document_evidence(checkpoint)
            artifacts = self._rebind_document_evidence(
                checkpoint,
                analysis,
                objective=active_objective,
                objective_inputs=document_objective_inputs,
            )
            await report_document_completed(document_input.document_id)
            return artifacts

        document_artifacts = await gather(
            *(
                inspect_document(document_input)
                for document_input in analysis.document_inputs
            )
        )
        contributions = tuple(item.contribution for item in document_artifacts)
        evidence_records = tuple(
            evidence
            for item in document_artifacts
            for evidence in item.evidence_records
        )
        findings = await to_thread(
            self.finding_synthesis_service.synthesize,
            collection_id=collection_id,
            objective=active_objective,
            analysis=analysis,
            contributions=contributions,
            evidence_records=evidence_records,
        )
        return ObjectiveAnalysisArtifacts(
            contributions=contributions,
            evidence_records=evidence_records,
            findings=findings,
            model_name=model_name,
            experiments=tuple(
                experiment
                for item in document_artifacts
                for experiment in item.experiments
            ),
        )

    def _generate_document_evidence(
        self,
        *,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        objective: ResearchObjective,
        objective_inputs: ObjectiveAnalysisInputs,
        progress_callback: ProgressCallback | None,
    ) -> ObjectiveDocumentEvidenceArtifacts:
        screened_sources = screen_sources(
            collection_id=collection_id,
            source_screener=self._objective_source_screener,
            objectives=(objective,),
            paper_maps=objective_inputs["paper_maps"],
            documents=objective_inputs["documents"],
            profiles_by_document_id=objective_inputs["profiles_by_document_id"],
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            progress_callback=progress_callback,
        )
        source_inspection_routes = route_sources(
            collection_id=collection_id,
            objectives=(objective,),
            objective_paper_frames=screened_sources,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            progress_callback=progress_callback,
        )
        read_audits: list[SourceReadAudit] = []
        validated_source_facts = extract_and_validate_source_facts(
            collection_id=collection_id,
            read_audits=read_audits,
            source_extractor=self._objective_source_extractor,
            paper_facts_extractor=self._paper_facts_extractor,
            objectives=(objective,),
            objective_paper_frames=screened_sources,
            objective_evidence_routes=source_inspection_routes,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            table_cells_by_document_id=objective_inputs["table_cells_by_document_id"],
            progress_callback=progress_callback,
        )
        paper_evidence_drafts = reconstruct_paper_experiments(
            collection_id=collection_id,
            source_facts=validated_source_facts,
            objectives=(objective,),
            document_contexts=self._document_contexts_for_evidence(
                blocks_by_document_id=objective_inputs["blocks_by_document_id"],
                tables_by_document_id=objective_inputs["tables_by_document_id"],
                figures_by_document_id=objective_inputs["figures_by_document_id"],
            ),
        )
        experiments = assemble_paper_experiments(
            collection_id=collection_id,
            document_id=objective_inputs["documents"][0].document_id,
            source_facts=paper_evidence_drafts,
        )
        evidence_records, contributions = materialize_evidence(
            collection_id=collection_id,
            analysis=analysis,
            objective=objective,
            observations=paper_evidence_drafts,
            technical_audits=tuple(read_audits),
            paper_maps=objective_inputs["paper_maps"],
            frames=screened_sources,
            routes=source_inspection_routes,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            figures_by_document_id=objective_inputs["figures_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            experiments=experiments,
        )
        if len(contributions) != 1:
            raise RuntimeError(
                "document Evidence extraction requires one paper contribution"
            )
        return ObjectiveDocumentEvidenceArtifacts(
            contribution=contributions[0],
            evidence_records=evidence_records,
            experiments=experiments,
        )

    @staticmethod
    def _document_contexts_for_evidence(
        *,
        blocks_by_document_id: Mapping[str, Sequence[SourceBlock]],
        tables_by_document_id: Mapping[str, Sequence[SourceTable]],
        figures_by_document_id: Mapping[str, Sequence[SourceFigure]],
    ) -> dict[str, tuple[dict[str, Any], ...]]:
        """Expose bounded, resolvable same-paper context to reconstruction.

        A result is often separated from its material or condition by a table
        or figure caption.  Keep those artifacts in the same context stream as
        text blocks so reconstruction has the information a researcher would
        have while reading the paper.  Source identity remains explicit and
        no context is imported from another document.
        """

        contexts: dict[str, tuple[dict[str, Any], ...]] = {}
        document_ids = tuple(
            dict.fromkeys(
                (
                    *blocks_by_document_id.keys(),
                    *tables_by_document_id.keys(),
                    *figures_by_document_id.keys(),
                )
            )
        )
        for document_id in document_ids:
            ranked: list[tuple[int, int, dict[str, Any]]] = []
            blocks = blocks_by_document_id.get(document_id, ())
            for position, block in enumerate(blocks):
                text = str(getattr(block, "text", "") or "").strip()
                source_ref = str(getattr(block, "block_id", "") or "").strip()
                if not text or not source_ref:
                    continue
                block_type = str(getattr(block, "block_type", "") or "").casefold()
                heading = str(getattr(block, "heading_path", "") or "").casefold()
                priority = (
                    0
                    if block_type == "title"
                    else 1
                    if "abstract" in heading
                    else 2
                    if any(
                        marker in heading
                        for marker in ("method", "material", "experimental")
                    )
                    else 3
                )
                ranked.append(
                    (
                        priority,
                        position,
                        {
                            "source_kind": "text_window",
                            "source_ref": source_ref,
                            "page": getattr(block, "page", None),
                            "heading_path": getattr(block, "heading_path", None),
                            "text": text,
                        },
                    )
                )
            for position, table in enumerate(
                tables_by_document_id.get(document_id, ())
            ):
                table_id = str(getattr(table, "table_id", "") or "").strip()
                if not table_id:
                    continue
                caption_text = str(getattr(table, "caption_text", "") or "").strip()
                heading_path = getattr(table, "heading_path", None)
                column_headers = tuple(
                    str(value).strip()
                    for value in (getattr(table, "column_headers", ()) or ())
                    if str(value).strip()
                )
                matrix = tuple(
                    tuple(str(cell).strip() for cell in row)
                    for row in (getattr(table, "table_matrix", ()) or ())
                    if isinstance(row, (list, tuple))
                )
                table_markdown = ""
                table_text = ""
                table_visual_text = ""
                to_record = getattr(table, "to_record", None)
                if callable(to_record):
                    record = to_record()
                    table_markdown = str(record.get("table_markdown") or "").strip()
                    table_text = str(record.get("table_text") or "").strip()
                    metadata = record.get("metadata")
                    if isinstance(metadata, dict):
                        table_visual_text = str(
                            metadata.get("visual_text") or ""
                        ).strip()
                if not table_markdown:
                    table_markdown = str(
                        render_markdown_table(
                            [list(row) for row in matrix],
                            list(column_headers),
                            header_row_count=int(
                                getattr(table, "header_row_count", 1) or 0
                            ),
                        )
                        or ""
                    ).strip()
                if not table_text:
                    table_text = str(
                        render_plain_table_text([list(row) for row in matrix]) or ""
                    ).strip()
                text = "\n".join(
                    part
                    for part in (
                        caption_text,
                        table_markdown or table_text,
                        table_visual_text,
                    )
                    if part
                ).strip()
                if not text:
                    continue
                heading = str(heading_path or "").casefold()
                caption = caption_text.casefold()
                priority = (
                    2
                    if any(
                        marker in heading or marker in caption
                        for marker in (
                            "result",
                            "mechanical",
                            "microstructure",
                            "material",
                            "method",
                            "experimental",
                        )
                    )
                    else 3
                )
                ranked.append(
                    (
                        priority,
                        len(blocks) + position,
                        {
                            "source_kind": "table",
                            "source_ref": table_id,
                            "page": getattr(table, "page", None),
                            "heading_path": heading_path,
                            "caption_text": caption_text or None,
                            "column_headers": list(column_headers),
                            "table_matrix": [list(row) for row in matrix],
                            "table_markdown": table_markdown or None,
                            "table_visual_text": table_visual_text or None,
                            "table_text": table_text or None,
                            "text": text,
                        },
                    )
                )
            for position, figure in enumerate(
                figures_by_document_id.get(document_id, ())
            ):
                figure_id = str(getattr(figure, "figure_id", "") or "").strip()
                caption_text = str(getattr(figure, "caption_text", "") or "").strip()
                if not figure_id or not caption_text:
                    continue
                heading_path = getattr(figure, "heading_path", None)
                heading = str(heading_path or "").casefold()
                caption = caption_text.casefold()
                priority = (
                    2
                    if any(
                        marker in heading or marker in caption
                        for marker in (
                            "result",
                            "mechanical",
                            "microstructure",
                            "material",
                            "method",
                            "experimental",
                        )
                    )
                    else 3
                )
                ranked.append(
                    (
                        priority,
                        len(blocks) + len(tables_by_document_id.get(document_id, ())) + position,
                        {
                            "source_kind": "figure",
                            "source_ref": figure_id,
                            "page": getattr(figure, "page", None),
                            "heading_path": heading_path,
                            "figure_label": getattr(figure, "figure_label", None),
                            "caption_text": caption_text,
                            "text": caption_text,
                        },
                    )
                )
            ranked.sort(key=lambda item: (item[0], item[1]))
            contexts[document_id] = tuple(
                item[2] for item in ranked[:_OBJECTIVE_DOCUMENT_CONTEXT_LIMIT]
            )
        return contexts

    @staticmethod
    def _document_evidence_input_fingerprint(
        *,
        objective: ResearchObjective,
        document_input: PreparedDocumentInput,
        model_name: str,
        extraction_version: str,
        scientific_versions: tuple[tuple[str, str], ...] = (
            OBJECTIVE_DOCUMENT_EVIDENCE_SCIENTIFIC_VERSIONS
        ),
    ) -> str:
        payload = {
            "objective": {
                "question": objective.question,
                "material_scope": list(objective.material_scope),
                "variables": list(objective.variables),
                "outcomes": list(objective.outcomes),
                "mechanisms": list(objective.mechanisms),
                "constraints": list(objective.constraints),
                "requested_comparator": objective.requested_comparator,
                "source_relationship_ids": list(objective.source_relationship_ids),
                "excluded_document_ids": list(objective.excluded_document_ids),
            },
            "document": document_input.to_record(),
            "extraction_version": extraction_version,
            "scientific_versions": dict(scientific_versions),
            "model_name": model_name,
        }
        return sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _objective_inputs_for_document(
        collection_id: str,
        objective_inputs: ObjectiveAnalysisInputs,
        document_id: str,
    ) -> ObjectiveAnalysisInputs:
        documents = tuple(
            item
            for item in objective_inputs["documents"]
            if item.document_id == document_id
        )
        paper_maps = tuple(
            item
            for item in objective_inputs["paper_maps"]
            if item.document_id == document_id
        )
        if len(documents) != 1 or len(paper_maps) != 1:
            raise ResearchObjectivesNotReadyError(collection_id)
        return {
            "documents": documents,
            "paper_maps": paper_maps,
            "profiles_by_document_id": {
                document_id: objective_inputs["profiles_by_document_id"][document_id]
            },
            "blocks_by_document_id": {
                document_id: objective_inputs["blocks_by_document_id"][document_id]
            },
            "tables_by_document_id": {
                document_id: objective_inputs["tables_by_document_id"][document_id]
            },
            "table_cells_by_document_id": {
                document_id: objective_inputs["table_cells_by_document_id"][document_id]
            },
            "figures_by_document_id": {
                document_id: objective_inputs["figures_by_document_id"][document_id]
            },
            "document_trees_by_document_id": {
                document_id: objective_inputs["document_trees_by_document_id"][
                    document_id
                ]
            },
        }

    @staticmethod
    def _rebind_document_evidence(
        checkpoint: ObjectiveDocumentEvidence,
        analysis: ObjectiveAnalysis,
        *,
        objective: ResearchObjective,
        objective_inputs: ObjectiveAnalysisInputs,
    ) -> ObjectiveDocumentEvidenceArtifacts:
        if checkpoint.contribution is None:
            raise ValueError("terminal document Evidence lacks a contribution")
        evidence_records = rebind_persisted_evidence(
            collection_id=checkpoint.collection_id,
            analysis=analysis,
            objective=objective,
            evidence_records=checkpoint.evidence_records,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            figures_by_document_id=objective_inputs["figures_by_document_id"],
        )
        contribution = rebind_persisted_contribution(
            contribution=checkpoint.contribution,
            analysis=analysis,
            objective=objective,
            evidence_records=evidence_records,
        )
        return ObjectiveDocumentEvidenceArtifacts(
            contribution=contribution,
            evidence_records=evidence_records,
        )

    @staticmethod
    def _failed_document_contribution(
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        document_id: str,
    ) -> PaperContribution:
        return PaperContribution(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            document_id=document_id,
            analysis_status="failed",
            relevance="uncertain",
            paper_role="uncertain",
            contribution_summary=None,
            material_match=(),
            changed_variables=(),
            measured_property_scope=(),
            test_environment_scope=(),
            exclusion_reason=None,
            warnings=(
                "Evidence extraction failed for this paper; retry the analysis.",
            ),
            confidence=0,
        )

    async def _build_objective_analysis_inputs(
        self,
        collection_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
    ) -> ObjectiveAnalysisInputs:
        source_inputs = await self.objective_input_service.load_source_inputs(
            collection_id,
            document_inputs=document_inputs,
        )
        paper_maps = await self.objective_input_service.load_or_build_paper_maps(
            collection_id,
            document_inputs=document_inputs,
            source_inputs=source_inputs,
        )
        return {
            **source_inputs,
            "paper_maps": paper_maps,
        }

__all__ = [
    "OBJECTIVE_DOCUMENT_EVIDENCE_SCIENTIFIC_VERSIONS",
    "ObjectiveEvidenceAnalysisService",
    "ResearchObjectivesNotReadyError",
]
