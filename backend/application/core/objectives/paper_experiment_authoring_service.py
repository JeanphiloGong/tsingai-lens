"""Source-grounded Agent authoring for one paper's experiment revisions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from application.core.objectives.analysis.experiment_analysis_writer import (
    ExperimentAnalysisWriter,
    ExperimentAnalysisWriteResult,
)
from application.core.objectives.analysis.paper_experiment_contract import (
    PaperExperimentDraftValidationError,
    PaperExperimentModelOutput,
    ReconciledPaperExperimentOutput,
    prepare_model_output,
)
from application.core.objectives.analysis.paper_experiment_extraction import (
    build_source_bundle,
)
from application.source.collection_service import CollectionService
from infra.persistence.postgres.experiment_analysis_transaction import (
    PostgresExperimentAnalysisTransactionFactory,
)
from repositories.source_artifact_repository import SourceArtifactRepository


@dataclass(frozen=True)
class PreparedPaperExperimentDraft:
    collection_id: str
    output: ReconciledPaperExperimentOutput
    source_fingerprint: str
    draft_digest: str
    source_digests: Mapping[tuple[str, str], str]


class PaperExperimentAuthoringError(ValueError):
    """A recoverable PaperExperiment authoring prerequisite failed."""

    error_code = "paper_experiment_authoring_failed"


class PaperExperimentDraftEmptyError(PaperExperimentAuthoringError):
    error_code = "paper_experiment_draft_empty"


class PaperExperimentSourceChangedError(PaperExperimentAuthoringError):
    error_code = "paper_experiment_source_changed"


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _source_digest_map(payloads: tuple[Mapping[str, Any], ...]) -> dict[tuple[str, str], str]:
    return {
        (str(source["source_kind"]), str(source["source_ref"])): sha256(
            str(source["_canonical_content"]).encode("utf-8")
        ).hexdigest()
        for source in payloads
    }


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
    """Validate paper facts and save the reviewed revisions independently."""

    def __init__(
        self,
        *,
        collection_service: CollectionService,
        source_artifact_repository: SourceArtifactRepository,
        experiment_analysis_writer: ExperimentAnalysisWriter,
        experiment_analysis_transaction_factory: PostgresExperimentAnalysisTransactionFactory | None = None,
    ) -> None:
        self.collection_service = collection_service
        self.source_artifact_repository = source_artifact_repository
        self.experiment_analysis_writer = experiment_analysis_writer
        self.experiment_analysis_transaction_factory = experiment_analysis_transaction_factory

    async def prepare(
        self,
        *,
        collection_id: str,
        user_id: str,
        document_id: str,
        raw_draft: Mapping[str, Any],
    ) -> PreparedPaperExperimentDraft:
        await self.collection_service.get_collection_for_user(collection_id, user_id)
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
            document_record.document.preparation_fingerprint
            or document_record.document.source_fingerprint
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
        try:
            output = PaperExperimentModelOutput.from_model_mapping(
                raw_draft,
                document_id=document_id,
                source_fingerprint=source_fingerprint,
                source_labels=bundle.source_catalog,
            )
            reconciled = prepare_model_output(output)
        except PaperExperimentDraftValidationError:
            raise
        except ValueError as exc:
            detail = " ".join(str(exc).split())
            path = detail.split(" ", 1)[0] if detail.startswith("experiments[") else None
            raise PaperExperimentDraftValidationError(
                detail or "PaperExperiment draft failed deterministic validation.",
                validation_path=path,
            ) from exc
        if not reconciled.output.experiments:
            raise PaperExperimentDraftEmptyError(
                "Agent draft contains no source-supported experiment"
            )
        digest = _canonical_digest(
            {
                "collection_id": collection_id,
                "document_id": document_id,
                "source_fingerprint": source_fingerprint,
                "source_catalog": bundle.source_catalog,
                "draft": raw_draft,
            }
        )
        return PreparedPaperExperimentDraft(
            collection_id=collection_id,
            output=reconciled,
            source_fingerprint=source_fingerprint,
            draft_digest=digest,
            source_digests=_source_digest_map(source_payloads),
        )

    async def write(
        self,
        *,
        prepared: PreparedPaperExperimentDraft,
        collection_id: str,
        created_by: str,
    ) -> ExperimentAnalysisWriteResult:
        if self.experiment_analysis_transaction_factory is None:
            raise RuntimeError(
                "PaperExperiment authoring requires an atomic revision transaction"
            )
        if prepared.collection_id != collection_id:
            raise ValueError("prepared paper experiment belongs to another collection")
        await self.collection_service.get_collection_for_user(collection_id, created_by)
        document_record = await self.collection_service.get_document(
            collection_id, prepared.output.output.document_id
        )
        document = await self.source_artifact_repository.read_document(
            collection_id, prepared.output.output.document_id
        )
        if document is None:
            raise FileNotFoundError("prepared Source document is no longer available")
        current_fingerprint = str(
            document_record.document.preparation_fingerprint
            or document_record.document.source_fingerprint
            or document.metadata.get("source_fingerprint")
            or ""
        ).strip()
        if current_fingerprint != prepared.source_fingerprint:
            raise PaperExperimentSourceChangedError(
                "prepared paper experiment source fingerprint changed; review it again"
            )
        current_digests = _source_digest_map(_source_payloads(document))
        if current_digests != dict(prepared.source_digests):
            raise PaperExperimentSourceChangedError(
                "prepared paper experiment Source content changed; review it again"
            )
        async with self.experiment_analysis_transaction_factory.begin() as transaction:
            return await self.experiment_analysis_writer.write_paper_experiment_revisions(
                experiment_outputs=(prepared.output,),
                created_by=created_by,
                transaction=transaction,
            )


__all__ = [
    "PaperExperimentAuthoringError",
    "PaperExperimentDraftEmptyError",
    "PaperExperimentSourceChangedError",
    "PaperExperimentAuthoringService",
    "PreparedPaperExperimentDraft",
]
