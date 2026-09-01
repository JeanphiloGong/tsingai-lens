"""Publish researcher-confirmed Evidence from one exact paper Source."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import re
import unicodedata
from typing import Any, Mapping
from uuid import uuid4

from application.source.collection_service import CollectionService
from domain.core import ObjectiveAnalysis, ObjectiveEvidence
from domain.ports import ObjectiveRepository, SourceArtifactRepository


_PAGE_SIZE = 500


@dataclass(frozen=True)
class EvidenceAuthoringResult:
    analysis: ObjectiveAnalysis
    evidence: ObjectiveEvidence


@dataclass(frozen=True)
class _CanonicalSource:
    content: str
    page: int | None


class EvidenceAuthoringService:
    """Create one immutable Evidence analysis version after Source verification."""

    def __init__(
        self,
        *,
        collection_service: CollectionService,
        objective_repository: ObjectiveRepository,
        source_artifact_repository: SourceArtifactRepository,
    ) -> None:
        self.collection_service = collection_service
        self.objective_repository = objective_repository
        self.source_artifact_repository = source_artifact_repository

    async def create_version(
        self,
        *,
        collection_id: str,
        objective_id: str,
        source_analysis_version: int,
        document_id: str,
        source_kind: str,
        source_ref: str,
        source_excerpt: str,
        evidence_role: str,
        changed_variables: tuple[Mapping[str, Any], ...],
        comparison: Mapping[str, Any] | None,
        reported_result: Mapping[str, Any] | None,
        attribution_scope: str,
        scientific_context: Mapping[str, Any],
        supersedes_evidence_id: str | None,
        authoring_note: str | None,
        source_digest: str | None = None,
        created_by_user_id: str,
    ) -> EvidenceAuthoringResult:
        await self.collection_service.get_collection_for_user(
            collection_id, created_by_user_id
        )
        objective = await self.objective_repository.read_objective(
            collection_id, objective_id
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        if objective.published_analysis_version != source_analysis_version:
            raise ValueError("source analysis version is stale")
        source_analysis = await self.objective_repository.read_analysis(
            collection_id, objective_id, source_analysis_version
        )
        if source_analysis is None or source_analysis.status != "succeeded":
            raise ValueError("source analysis version is not available")
        active = await self.objective_repository.read_analysis(
            collection_id, objective_id, objective.active_analysis_version
        )
        if active is not None and active.analysis_version != source_analysis_version:
            if active.status in {"queued", "running"}:
                raise ValueError("objective analysis is currently running")

        document_ids = {item.document_id for item in source_analysis.document_inputs}
        if document_id not in document_ids:
            raise ValueError("Source document is outside the analysis document scope")
        source_contributions = await self.objective_repository.list_contributions(
            collection_id, objective_id, source_analysis_version
        )
        if document_id not in {item.document_id for item in source_contributions}:
            raise ValueError("Source document has no contribution in this analysis")

        source_document = await self.source_artifact_repository.read_document(
            collection_id, document_id
        )
        if source_document is None:
            raise FileNotFoundError("Source document was not found")
        canonical = self._resolve_source(
            source_document, source_kind=source_kind, source_ref=source_ref
        )
        normalized_excerpt = self._normalized(source_excerpt)
        if not normalized_excerpt:
            raise ValueError("Source excerpt is required")
        if normalized_excerpt not in self._normalized(canonical.content):
            raise ValueError("Source excerpt is not contained in the canonical Source")
        if source_digest is not None:
            digest = hashlib.sha256(canonical.content.encode("utf-8")).hexdigest()
            if source_digest != digest:
                raise ValueError("Source verification token does not match the canonical Source")

        source_evidence = await self._all_evidence(
            collection_id, objective_id, source_analysis_version
        )
        revision = None
        if supersedes_evidence_id:
            revision = next(
                (
                    item
                    for item in source_evidence
                    if item.evidence_id == supersedes_evidence_id
                ),
                None,
            )
            if revision is None:
                raise ValueError("revision Evidence was not found in the source analysis")
            if revision.superseded_by_evidence_id:
                raise ValueError("revision Evidence is no longer the current Source version")
            if (
                revision.document_id != document_id
                or revision.source_kind != source_kind
                or revision.source_ref != source_ref
            ):
                raise ValueError("revision Evidence must retain its exact Source locator")

        source_findings = await self._all_findings(
            collection_id, objective_id, source_analysis_version
        )
        target_version = max(
            source_analysis_version,
            objective.active_analysis_version or source_analysis_version,
        ) + 1
        evidence_id = f"evidence_manual_{uuid4().hex[:16]}"
        now = datetime.now(timezone.utc)
        authored = ObjectiveEvidence.from_mapping(
            {
                "collection_id": collection_id,
                "objective_id": objective_id,
                "analysis_version": target_version,
                "evidence_id": evidence_id,
                "document_id": document_id,
                "source_kind": source_kind,
                "source_ref": source_ref,
                "source_excerpt": source_excerpt.strip(),
                "page_numbers": [canonical.page] if canonical.page is not None else [],
                "related_source_refs": [],
                "evidence_role": evidence_role,
                "selection_status": "extracted",
                "selection_reason": self._clean_optional(authoring_note),
                "changed_variables": list(changed_variables),
                "comparison": comparison,
                "reported_result": reported_result,
                "attribution_scope": attribution_scope,
                "scientific_context": scientific_context,
                "anchor_ids": [],
                "resolution_status": "resolved",
                "failure_reason": None,
                "confidence": 1.0,
                "origin": "human_revised" if revision is not None else "human_authored",
                "source_analysis_version": source_analysis_version,
                "supersedes_evidence_id": (
                    revision.evidence_id if revision is not None else None
                ),
                "created_by_user_id": created_by_user_id,
                "created_at": now,
                "authoring_note": self._clean_optional(authoring_note),
            }
        )

        contributions = tuple(
            replace(item, analysis_version=target_version)
            for item in source_contributions
        )
        evidence_records = tuple(
            replace(
                item,
                analysis_version=target_version,
                superseded_by_evidence_id=(
                    authored.evidence_id
                    if revision is not None and item.evidence_id == revision.evidence_id
                    else item.superseded_by_evidence_id
                ),
            )
            for item in source_evidence
        ) + (authored,)
        findings = tuple(
            replace(
                item,
                analysis_version=target_version,
                source_analysis_version=(
                    item.source_analysis_version or source_analysis_version
                ),
            )
            for item in source_findings
        )
        analysis = ObjectiveAnalysis(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=target_version,
            document_inputs=source_analysis.document_inputs,
            pipeline_version=source_analysis.pipeline_version,
            model_name=source_analysis.model_name,
            prompt_versions=dict(source_analysis.prompt_versions),
            stats=source_analysis.stats,
            status="succeeded",
            phase="completed",
            processed_document_count=len(source_analysis.document_inputs),
            total_document_count=len(source_analysis.document_inputs),
            progress_message="Researcher-confirmed Evidence version completed.",
            created_at=now,
            started_at=now,
            completed_at=now,
            diagnostics=source_analysis.diagnostics,
            origin="hybrid",
            source_analysis_version=source_analysis_version,
            created_by_user_id=created_by_user_id,
        )
        _objective, published = (
            await self.objective_repository.publish_authored_analysis(
                collection_id,
                objective_id,
                source_analysis_version,
                analysis=analysis,
                contributions=contributions,
                evidence_records=evidence_records,
                findings=findings,
            )
        )
        return EvidenceAuthoringResult(analysis=published, evidence=authored)

    @staticmethod
    def _resolve_source(
        document: Any, *, source_kind: str, source_ref: str
    ) -> _CanonicalSource:
        if source_kind == "text_window":
            source = next(
                (item for item in document.blocks if item.block_id == source_ref), None
            )
            if source is not None:
                return _CanonicalSource(content=source.text, page=source.page)
        elif source_kind == "table":
            source = next(
                (item for item in document.tables if item.table_id == source_ref), None
            )
            if source is not None:
                record = source.to_record()
                return _CanonicalSource(
                    # The table Markdown is the canonical table Source. The
                    # caption remains available as table metadata and is not
                    # mixed into the hashed content returned by the Agent.
                    content=str(record["table_markdown"] or "").strip(),
                    page=source.page,
                )
        elif source_kind == "figure":
            source = next(
                (item for item in document.figures if item.figure_id == source_ref), None
            )
            if source is not None:
                return _CanonicalSource(
                    content=str(source.caption_text or ""), page=source.page
                )
        else:
            raise ValueError(f"unsupported objective evidence source: {source_kind}")
        raise FileNotFoundError("Source was not found in the requested document")

    async def _all_evidence(
        self, collection_id: str, objective_id: str, analysis_version: int
    ) -> tuple[ObjectiveEvidence, ...]:
        records: list[ObjectiveEvidence] = []
        while True:
            page, total = await self.objective_repository.list_evidence(
                collection_id,
                objective_id,
                analysis_version,
                offset=len(records),
                limit=_PAGE_SIZE,
            )
            records.extend(page)
            if len(records) >= total:
                return tuple(records)
            if not page:
                raise RuntimeError("objective Evidence pagination did not advance")

    async def _all_findings(
        self, collection_id: str, objective_id: str, analysis_version: int
    ) -> tuple[Any, ...]:
        records: list[Any] = []
        while True:
            page, total = await self.objective_repository.list_findings(
                collection_id,
                objective_id,
                analysis_version,
                offset=len(records),
                limit=_PAGE_SIZE,
            )
            records.extend(page)
            if len(records) >= total:
                return tuple(records)
            if not page:
                raise RuntimeError("objective Finding pagination did not advance")

    @staticmethod
    def _normalized(value: str) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        cleaned = " ".join(str(value or "").split())
        return cleaned or None


__all__ = ["EvidenceAuthoringResult", "EvidenceAuthoringService"]
