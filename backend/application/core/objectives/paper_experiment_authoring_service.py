"""Source-grounded Agent authoring for one PaperExperiment revision."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, Mapping

from application.core.objectives.analysis.experiment_analysis_writer import (
    ExperimentAnalysisWriter,
    ExperimentAnalysisWriteResult,
)
from application.core.objectives.analysis.paper_experiment_contract import (
    PaperExperimentModelOutput,
    ReconciledPaperExperimentOutput,
    prepare_model_output,
)
from application.core.objectives.analysis.paper_experiment_extraction import (
    build_source_bundle,
)
from application.repositories.objective_repository import (
    ObjectiveAnalysis,
    ObjectiveRepository,
)
from application.repositories.source_artifact_repository import SourceArtifactRepository
from application.repositories.transaction import RepositoryTransactionFactory
from application.source.collection_service import CollectionService
from domain.core.research_objective import ResearchObjective


@dataclass(frozen=True)
class PreparedPaperExperimentDraft:
    objective: ResearchObjective
    analysis: ObjectiveAnalysis
    output: ReconciledPaperExperimentOutput
    source_fingerprint: str
    draft_digest: str
    source_digests: Mapping[str, str]


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _source_payloads(document: Any) -> tuple[Mapping[str, Any], ...]:
    payloads: list[Mapping[str, Any]] = []
    for block in sorted(document.blocks, key=lambda item: item.block_order):
        if str(block.text or "").strip():
            payloads.append(
                {
                    "source_type": "text",
                    "source_kind": "text_window",
                    "source_ref": block.block_id,
                    "page": block.page,
                    "heading_path": block.heading_path,
                    "block_type": str(block.block_type or "paragraph"),
                    "quote": str(block.text or ""),
                    "_canonical_content": str(block.text or ""),
                }
            )
    for table in sorted(document.tables, key=lambda item: item.table_order):
        record = table.to_record()
        payloads.append(
            {
                "source_type": "table",
                "source_kind": "table",
                "source_ref": table.table_id,
                "page": table.page,
                "heading_path": table.heading_path,
                "caption": table.caption_text,
                "row_count": table.row_count,
                "column_count": table.col_count,
                "quote": str(record.get("table_markdown") or "").strip(),
                "_canonical_content": str(record.get("table_markdown") or "").strip(),
            }
        )
    for figure in sorted(document.figures, key=lambda item: item.figure_order):
        if str(figure.caption_text or "").strip():
            payloads.append(
                {
                    "source_type": "figure",
                    "source_kind": "figure",
                    "source_ref": figure.figure_id,
                    "page": figure.page,
                    "heading_path": figure.heading_path,
                    "figure_label": figure.figure_label,
                    "quote": str(figure.caption_text or ""),
                    "_canonical_content": str(figure.caption_text or ""),
                }
            )
    return tuple(payloads)


class PaperExperimentAuthoringService:
    """Validate an Agent draft and hand one revision to the canonical writer."""

    def __init__(
        self,
        *,
        collection_service: CollectionService,
        source_artifact_repository: SourceArtifactRepository,
        objective_repository: ObjectiveRepository,
        experiment_analysis_writer: ExperimentAnalysisWriter,
        experiment_analysis_transaction_factory: RepositoryTransactionFactory | None = None,
    ) -> None:
        self.collection_service = collection_service
        self.source_artifact_repository = source_artifact_repository
        self.objective_repository = objective_repository
        self.experiment_analysis_writer = experiment_analysis_writer
        self.experiment_analysis_transaction_factory = experiment_analysis_transaction_factory

    async def prepare(
        self,
        *,
        collection_id: str,
        user_id: str,
        objective_id: str,
        document_id: str,
        raw_draft: Mapping[str, Any],
    ) -> PreparedPaperExperimentDraft:
        await self.collection_service.get_collection_for_user(collection_id, user_id)
        objective = await self.objective_repository.read_objective(
            collection_id, objective_id
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        if objective.confirmation_status != "confirmed":
            raise ValueError("confirm the research objective before authoring an experiment")
        if objective.active_analysis_version is None:
            raise ValueError(
                "start and publish an active Objective analysis before authoring an experiment"
            )
        analysis = await self.objective_repository.read_analysis(
            collection_id,
            objective_id,
            objective.active_analysis_version,
        )
        if analysis is None:
            raise ValueError("active Objective analysis could not be loaded")
        if analysis.status != "succeeded":
            raise ValueError("active Objective analysis is not a completed snapshot")
        document = await self.source_artifact_repository.read_document(
            collection_id, document_id
        )
        if document is None:
            raise FileNotFoundError(
                f"prepared Source document not found: {collection_id}/{document_id}"
            )
        document_record = await self.collection_service.get_document(
            collection_id, document_id
        )
        source_fingerprint = str(
            getattr(document_record, "preparation_fingerprint", None)
            or getattr(document_record, "source_fingerprint", None)
            or document.metadata.get("source_fingerprint")
            or ""
        ).strip()
        if not source_fingerprint:
            raise ValueError("prepared Source document has no fingerprint")
        source_payloads = _source_payloads(document)
        bundle = build_source_bundle(
            document_id=document_id,
            source_fingerprint=source_fingerprint,
            source_payloads=source_payloads,
        )
        output = PaperExperimentModelOutput.from_model_mapping(
            raw_draft,
            document_id=document_id,
            source_fingerprint=source_fingerprint,
            source_labels=bundle.source_catalog,
        )
        reconciled = prepare_model_output(output, objective=objective)
        if not reconciled.output.experiments:
            raise ValueError("Agent draft contains no source-supported experiment")
        digest = _canonical_digest(
            {
                "collection_id": collection_id,
                "objective_id": objective_id,
                "source_analysis_version": analysis.analysis_version,
                "document_id": document_id,
                "source_fingerprint": source_fingerprint,
                "draft": raw_draft,
            }
        )
        return PreparedPaperExperimentDraft(
            objective=objective,
            analysis=analysis,
            output=reconciled,
            source_fingerprint=source_fingerprint,
            draft_digest=digest,
            source_digests={
                str(source["source_ref"]): sha256(
                    str(source["_canonical_content"]).encode("utf-8")
                ).hexdigest()
                for source in source_payloads
            },
        )

    async def write(
        self,
        *,
        prepared: PreparedPaperExperimentDraft,
        collection_id: str,
        created_by: str,
        created_by_tool_call_id: str,
    ) -> ExperimentAnalysisWriteResult:
        if self.experiment_analysis_transaction_factory is None:
            raise RuntimeError(
                "PaperExperiment authoring requires a shared analysis transaction"
            )
        coverage = await self.objective_repository.list_contributions(
            collection_id, prepared.objective.objective_id,
            prepared.analysis.analysis_version,
        )
        _objective, queued = await self.objective_repository.queue_analysis(
            collection_id,
            prepared.objective.objective_id,
            document_inputs=prepared.analysis.document_inputs,
            pipeline_version=prepared.analysis.pipeline_version,
            model_name=prepared.analysis.model_name,
            prompt_versions=dict(prepared.analysis.prompt_versions),
            origin="agent_authored",
            created_by_user_id=created_by,
            created_by_tool_call_id=created_by_tool_call_id,
            source_analysis_version=prepared.analysis.analysis_version,
        )
        claimed = await self.objective_repository.claim_analysis(
            collection_id,
            prepared.objective.objective_id,
            queued.analysis_version,
        )
        if claimed is None:
            raise ValueError("agent experiment analysis snapshot could not be claimed")
        try:
            async with self.experiment_analysis_transaction_factory.begin() as transaction:
                result = await self.experiment_analysis_writer.write_single_experiment_revision(
                    collection_id=collection_id,
                    objective=prepared.objective,
                    analysis=claimed,
                    experiment_output=prepared.output,
                    create_selection=True,
                    created_by=created_by,
                    transaction=transaction,
                )
                await self.objective_repository.publish_experiment_analysis(
                    collection_id,
                    prepared.objective.objective_id,
                    claimed.analysis_version,
                    contributions=tuple(
                        replace(item, analysis_version=claimed.analysis_version)
                        for item in coverage
                    ),
                    transaction=transaction,
                )
        except Exception as exc:
            await self.objective_repository.fail_analysis(
                collection_id,
                prepared.objective.objective_id,
                claimed.analysis_version,
                error_code="authored_experiment_publish_failed",
                error_message=str(exc),
                expected_status="running",
            )
            raise
        return result


__all__ = ["PaperExperimentAuthoringService", "PreparedPaperExperimentDraft"]
