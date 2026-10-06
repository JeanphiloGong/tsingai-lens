from __future__ import annotations

import logging
from asyncio import Semaphore, gather, to_thread
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Sequence

from application.core.objectives.analysis.diagnostics import record_analysis_failure
from application.core.objectives.analysis.evidence_routing import route_sources
from application.core.objectives.analysis.paper_experiment_contract import (
    ReconciledPaperExperimentOutput,
)
from application.core.objectives.analysis.paper_experiment_extraction import (
    PaperExperimentExtractionResult,
    PaperExperimentExtractor,
    build_bundle_from_routes,
)
from application.core.objectives.analysis.source_screening import (
    ObjectiveSourceScreener,
    PaperAnalysisFrame,
    screen_sources,
)
from application.core.objectives.objective_input_service import (
    ObjectiveInputService,
    ObjectiveSourceInputs,
    ResearchObjectivesNotReadyError,
)
from application.core.objectives.scope_screening import (
    ObjectiveScopePreview,
    screen_objective_scope,
)
from application.repositories.objective_repository import (
    ObjectiveAnalysis,
    ObjectiveRepository,
)
from application.repositories.paper_map_repository import PaperMapRepository
from application.source.collection_service import CollectionService
from domain.core import (
    InspectedObjectiveSourceRef,
    PaperContribution,
    PaperResearchMap,
    PreparedDocumentInput,
    ResearchObjective,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


class ObjectiveAnalysisInputs(ObjectiveSourceInputs):
    """The selected prepared Sources plus their Paper Map navigation priors."""

    paper_maps: tuple[PaperResearchMap, ...]


_OBJECTIVE_DOCUMENT_MAX_CONCURRENCY = 4
# Keep concurrent document extraction bounded so one Objective run cannot
# overwhelm the provider or the worker process.


_SOURCE_KIND_ALIASES = {
    "block": "text_window",
    "paragraph": "text_window",
    "text": "text_window",
    "text_window": "text_window",
    "table": "table",
    "table_row": "table",
    "table_cell": "table",
    "figure": "figure",
    "figure_caption": "figure",
}


def _source_ref(value: Mapping[str, Any]) -> InspectedObjectiveSourceRef:
    kind = str(value.get("source_kind") or "").strip().casefold()
    return InspectedObjectiveSourceRef(
        source_kind=_SOURCE_KIND_ALIASES.get(kind, kind),
        source_ref=str(value.get("source_ref") or "").strip(),
        source_digest=(
            str(value.get("source_digest") or "").strip().lower() or None
        ),
    )


def _unique_source_refs(
    values: Sequence[Mapping[str, Any]],
) -> tuple[InspectedObjectiveSourceRef, ...]:
    result: list[InspectedObjectiveSourceRef] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        ref = _source_ref(value)
        identity = (ref.source_kind, ref.source_ref)
        if not ref.source_ref or identity in seen:
            continue
        seen.add(identity)
        result.append(ref)
    return tuple(result)


def _used_draft_source_labels(output: ReconciledPaperExperimentOutput) -> set[str]:
    labels: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if key in {"unresolved_issues", "audit_issues"}:
                    continue
                if key == "source_label" and isinstance(nested, str):
                    labels.add(nested.strip())
                    continue
                if key in {
                    "source_labels",
                    "binding_source_labels",
                    "variant_binding_source_labels",
                    "test_binding_source_labels",
                    "interpretation_source_labels",
                }:
                    # Most source fields are lists of local labels.  Keep
                    # accepting nested mappings here because Draft-only
                    # boundary evidence may carry ``source_label`` objects
                    # alongside an explanation.  Treating a mapping as a
                    # string would produce ``{"source_label": "S001"}``
                    # and under-count extracted Source coverage.
                    if isinstance(nested, (list, tuple, set)):
                        for item in nested:
                            if isinstance(item, str):
                                labels.add(item.strip())
                            else:
                                visit(item)
                    else:
                        visit(nested)
                    continue
                if key == "split_evidence":
                    # Boundary evidence is a nested Draft shape rather than
                    # a flat list of labels; recurse so its source_label(s)
                    # participate in Source accounting.
                    visit(nested)
                    continue
                visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)

    for draft in output.output.experiments:
        labels.update(draft.source_labels)
        visit(draft.payload)
    return labels


def _draft_measurements(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    values = payload.get("measurements") or ()
    return tuple(item for item in values if isinstance(item, Mapping))


def _build_contribution_for_extraction(
    *,
    collection_id: str,
    analysis: ObjectiveAnalysis,
    objective: ResearchObjective,
    frame: PaperAnalysisFrame | None,
    extraction: PaperExperimentExtractionResult,
    routed_source_refs: Sequence[Mapping[str, Any]],
    inspected_source_refs: Sequence[Mapping[str, Any]],
    failed_source_refs: Sequence[Mapping[str, Any]],
    omitted_source_refs: Sequence[str],
    comparable_evidence_count: int = 0,
) -> PaperContribution:
    """Build contribution accounting from Source identities, not call counts."""

    routed = _unique_source_refs(routed_source_refs)
    inspected = _unique_source_refs(inspected_source_refs)
    failed = _unique_source_refs(failed_source_refs)
    routed_ids = {(item.source_kind, item.source_ref) for item in routed}
    inspected_ids = {(item.source_kind, item.source_ref) for item in inspected}
    failed_ids = {(item.source_kind, item.source_ref) for item in failed}
    if not inspected_ids <= routed_ids or not failed_ids <= routed_ids:
        raise ValueError("Source accounting contains a ref that was not routed")
    if inspected_ids & failed_ids:
        raise ValueError("a Source cannot be both inspected and failed")

    omitted = tuple(
        dict.fromkeys(
            str(item).strip() for item in omitted_source_refs if str(item).strip()
        )
    )
    uninspected_ids = routed_ids - inspected_ids - failed_ids
    omitted_routed_ids = {
        identity for identity in routed_ids if identity[1] in omitted
    }
    omitted_outside_routes = {
        source_ref
        for source_ref in omitted
        if not any(identity[1] == source_ref for identity in routed_ids)
    }
    uninspected_count = len(uninspected_ids | omitted_routed_ids) + len(
        omitted_outside_routes
    )

    output = extraction.output
    used_labels = _used_draft_source_labels(output) if output is not None else set()
    extracted_ids: set[tuple[str, str]] = set()
    if output is not None:
        for label in used_labels:
            raw = output.output.source_labels.get(label)
            if isinstance(raw, Mapping):
                ref = _source_ref(raw)
                extracted_ids.add((ref.source_kind, ref.source_ref))
    extracted_count = len(extracted_ids & routed_ids)

    excluded_by_screening = bool(
        frame is not None
        and not routed
        and (
            frame.relevance == "irrelevant"
            or frame.paper_role in {"review", "irrelevant"}
        )
    )
    if excluded_by_screening:
        disposition = "excluded"
        analysis_status = "excluded"
    elif not routed:
        disposition = "no_routable_evidence"
        analysis_status = "analyzed"
    elif failed and extracted_count == 0 and comparable_evidence_count == 0:
        disposition = "extraction_failed"
        analysis_status = "failed"
    elif uninspected_count:
        disposition = "coverage_incomplete"
        analysis_status = "analyzed"
    elif comparable_evidence_count > 0:
        disposition = "comparable_evidence"
        analysis_status = "analyzed"
    elif extracted_count == 0:
        disposition = "no_grounded_evidence"
        analysis_status = "analyzed"
    else:
        disposition = "no_comparable_evidence"
        analysis_status = "analyzed"

    if extraction.status == "technical_failure" and not failed:
        raise RuntimeError(
            "technical extraction failure has no Source-level failed audit"
        )
    if disposition == "no_grounded_evidence" and inspected_ids != routed_ids:
        raise ValueError(
            "no_grounded_evidence requires every routed Source to be inspected"
        )

    diagnostics = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in extraction.diagnostics
            if str(item).strip()
        )
    )
    warnings = diagnostics
    if uninspected_count:
        warnings = (*warnings, f"{uninspected_count} routed Source(s) remain uninspected.")
    reason = {
        "excluded": (
            "The paper was screened out for this Objective and was not routed "
            "for experiment extraction."
        ),
        "no_routable_evidence": "No Source was routed for this Objective.",
        "no_grounded_evidence": "Routed Sources were inspected but no source-grounded experiment fact was recovered.",
        "no_comparable_evidence": "Experiment facts were recovered, but no bound comparable result is available.",
        "coverage_incomplete": "Some routed Source context was omitted or not inspected.",
        "extraction_failed": "One or more routed Sources failed during Source-level extraction.",
        "comparable_evidence": None,
    }[disposition]
    measured_scope = tuple(
        dict.fromkeys(
            str(item.get("outcome") or "").strip()
            for draft in (output.output.experiments if output is not None else ())
            for item in _draft_measurements(draft.payload)
            if str(item.get("outcome") or "").strip()
        )
    )
    document_id = (
        output.output.document_id
        if output is not None
        else (frame.document_id if frame is not None else "")
    )
    return PaperContribution(
        collection_id=collection_id,
        objective_id=objective.objective_id,
        analysis_version=analysis.analysis_version,
        document_id=document_id,
        analysis_status=analysis_status,
        relevance=frame.relevance if frame is not None else "uncertain",
        paper_role=frame.paper_role if frame is not None else "uncertain",
        contribution_summary=(
            f"Recovered {len(output.output.experiments)} PaperExperiment Draft series."
            if output is not None
            else None
        ),
        material_match=frame.material_match if frame is not None else (),
        changed_variables=frame.changed_variables if frame is not None else (),
        measured_property_scope=measured_scope
        or (frame.measured_property_scope if frame is not None else ()),
        test_environment_scope=frame.test_environment_scope if frame is not None else (),
        exclusion_reason=reason if disposition == "excluded" else None,
        warnings=warnings,
        confidence=0.9 if extracted_count else 0.0,
        evidence_disposition=disposition,
        routed_source_count=len(routed),
        extracted_source_count=(0 if disposition == "extraction_failed" else extracted_count),
        comparable_evidence_count=(
            0 if disposition == "extraction_failed" else comparable_evidence_count
        ),
        failed_source_count=len(failed),
        uninspected_source_count=uninspected_count,
        evidence_disposition_reason=reason,
        inspected_source_refs=inspected,
    )


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
        warnings=("PaperExperiment extraction failed for this paper; retry the analysis.",),
        confidence=0,
    )


@dataclass(frozen=True)
class ObjectiveExperimentAnalysisArtifacts:
    """Experiment inputs and coverage produced by one Objective analysis run."""

    contributions: tuple[PaperContribution, ...]
    experiment_outputs: tuple[ReconciledPaperExperimentOutput, ...] = ()
    partial_experiment_outputs: tuple[ReconciledPaperExperimentOutput, ...] = ()
    extraction_statuses: Mapping[str, str] = field(default_factory=dict)
    extraction_diagnostics: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    model_name: str | None = None


@dataclass(frozen=True)
class DocumentExperimentArtifacts:
    """Source inspection result for one Objective and one document."""

    contribution: PaperContribution
    experiment_outputs: tuple[ReconciledPaperExperimentOutput, ...] = ()
    partial_experiment_outputs: tuple[ReconciledPaperExperimentOutput, ...] = ()
    extraction_status: Literal[
        "ready", "partial_archive", "abstained", "technical_failure"
    ] = "abstained"
    extraction_diagnostics: tuple[str, ...] = ()


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


class ObjectiveExperimentAnalysisService:
    """Reconstruct source-grounded experiments for one confirmed Objective."""

    def __init__(
        self,
        collection_service: CollectionService,
        paper_map_repository: PaperMapRepository,
        objective_repository: ObjectiveRepository,
        objective_input_service: ObjectiveInputService,
        objective_source_screener: ObjectiveSourceScreener | None = None,
        paper_experiment_extractor: PaperExperimentExtractor | None = None,
    ) -> None:
        self.collection_service = collection_service
        self._objective_source_screener = objective_source_screener
        self._paper_experiment_extractor = paper_experiment_extractor
        self.paper_map_repository = paper_map_repository
        self.objective_repository = objective_repository
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

    async def generate_experiment_analysis_artifacts(
        self,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        progress_callback: ProgressCallback | None = None,
    ) -> ObjectiveExperimentAnalysisArtifacts:
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
        if self._paper_experiment_extractor is None:
            self._paper_experiment_extractor = PaperExperimentExtractor(response_client)
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
        ) -> DocumentExperimentArtifacts:
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
                        self._reconstruct_document_experiments,
                        collection_id=collection_id,
                        analysis=analysis,
                        objective=active_objective,
                        objective_inputs=document_objective_inputs,
                        progress_callback=document_progress_callback,
                    )
            except Exception as exc:  # noqa: BLE001
                record_analysis_failure(
                    exc,
                    collection_id=collection_id,
                    objective_id=active_objective.objective_id,
                    document_id=document_input.document_id,
                    stage="document_experiment_extraction",
                )
                logger.error(
                    "Objective document experiment extraction failed "
                    "collection_id=%s objective_id=%s document_id=%s error_type=%s",
                    collection_id,
                    active_objective.objective_id,
                    document_input.document_id,
                    type(exc).__name__,
                )
                artifacts = DocumentExperimentArtifacts(
                    contribution=_failed_document_contribution(
                        collection_id=collection_id,
                        objective_id=active_objective.objective_id,
                        analysis_version=analysis.analysis_version,
                        document_id=document_input.document_id,
                    ),
                    extraction_status="technical_failure",
                    extraction_diagnostics=(type(exc).__name__,),
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
        # Findings are synthesized only after immutable experiment revisions
        # and Objective selections have been written.  Keeping this stage
        # focused on Source reading prevents a second, legacy fact ledger from
        # becoming the source of the published conclusion.
        return ObjectiveExperimentAnalysisArtifacts(
            contributions=contributions,
            experiment_outputs=tuple(
                output
                for item in document_artifacts
                for output in item.experiment_outputs
            ),
            partial_experiment_outputs=tuple(
                output
                for item in document_artifacts
                for output in item.partial_experiment_outputs
            ),
            extraction_statuses={
                item.contribution.document_id: item.extraction_status
                for item in document_artifacts
            },
            extraction_diagnostics={
                item.contribution.document_id: item.extraction_diagnostics
                for item in document_artifacts
                if item.extraction_diagnostics
            },
            model_name=model_name,
        )

    def _reconstruct_document_experiments(
        self,
        *,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        objective: ResearchObjective,
        objective_inputs: ObjectiveAnalysisInputs,
        progress_callback: ProgressCallback | None,
    ) -> DocumentExperimentArtifacts:
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
        document_id = objective_inputs["documents"][0].document_id
        document_input = next(
            item
            for item in analysis.document_inputs
            if item.document_id == document_id
        )
        if self._paper_experiment_extractor is None:
            raise RuntimeError("PaperExperiment Draft extractor is not configured")
        bundle = build_bundle_from_routes(
            document_id=document_id,
            source_fingerprint=document_input.preparation_fingerprint,
            routes=source_inspection_routes,
            blocks=list(objective_inputs["blocks_by_document_id"].get(document_id, ())),
            tables=list(objective_inputs["tables_by_document_id"].get(document_id, ())),
            figures=list(objective_inputs["figures_by_document_id"].get(document_id, ())),
            document_tree=objective_inputs["document_trees_by_document_id"].get(document_id),
            table_cells=list(
                objective_inputs["table_cells_by_document_id"].get(document_id, ())
            ),
        )
        extraction = self._paper_experiment_extractor.extract(
            objective=objective,
            bundle=bundle,
        )
        frame = next(
            (
                item
                for item in screened_sources
                if item.document_id == document_id
            ),
            None,
        )
        routed_refs = tuple(
            {
                "source_kind": item.source_kind,
                "source_ref": item.source_ref,
            }
            for item in source_inspection_routes
            if item.extractable
        )
        # ``prompt_sources`` deliberately strips service identifiers before it
        # is sent to the model.  The server-side catalog is the authoritative
        # accounting source for what entered the read bundle.
        bundle_source_refs = tuple(bundle.source_catalog.values())
        inspected_refs = (
            bundle_source_refs
            if extraction.status != "technical_failure"
            else ()
        )
        failed_refs = (
            bundle_source_refs
            if extraction.status == "technical_failure"
            else ()
        )
        ready_outputs: tuple[ReconciledPaperExperimentOutput, ...] = ()
        partial_outputs: tuple[ReconciledPaperExperimentOutput, ...] = ()
        if extraction.output is not None:
            if extraction.status == "ready":
                ready_outputs = (extraction.output,)
            elif extraction.status == "partial_archive":
                partial_outputs = (extraction.output,)
        comparable_count = (
            len(extraction.readiness.selected_comparison_keys)
            if extraction.status == "ready" and extraction.readiness is not None
            else 0
        )
        contribution = _build_contribution_for_extraction(
            collection_id=collection_id,
            analysis=analysis,
            objective=objective,
            frame=frame,
            extraction=extraction,
            routed_source_refs=routed_refs,
            inspected_source_refs=inspected_refs,
            failed_source_refs=failed_refs,
            omitted_source_refs=bundle.omitted_source_refs,
            comparable_evidence_count=comparable_count,
        )
        return DocumentExperimentArtifacts(
            contribution=contribution,
            experiment_outputs=ready_outputs,
            partial_experiment_outputs=partial_outputs,
            extraction_status=extraction.status,
            extraction_diagnostics=extraction.diagnostics,
        )


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
    "DocumentExperimentArtifacts",
    "ObjectiveExperimentAnalysisArtifacts",
    "ObjectiveExperimentAnalysisService",
    "ResearchObjectivesNotReadyError",
]
