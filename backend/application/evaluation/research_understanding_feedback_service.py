from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1

from domain.evaluation import (
    ResearchUnderstandingCuration,
    ResearchUnderstandingFeedback,
)
from domain.ports import EvaluationRepository
from infra.persistence.factory import build_evaluation_repository


class ResearchUnderstandingFeedbackService:
    """Persist expert review feedback for research-understanding claims."""

    def __init__(
        self,
        evaluation_repository: EvaluationRepository | None = None,
    ) -> None:
        self.evaluation_repository = (
            evaluation_repository or build_evaluation_repository()
        )

    def record_feedback(
        self,
        *,
        collection_id: str,
        scope_type: str,
        scope_id: str,
        claim_id: str,
        review_status: str,
        issue_type: str,
        note: str | None = None,
        reviewer: str | None = None,
    ) -> ResearchUnderstandingFeedback:
        created_at = _now_iso()
        feedback = ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": _feedback_id(
                    collection_id,
                    scope_type,
                    scope_id,
                    claim_id,
                    review_status,
                    issue_type,
                    note,
                    reviewer,
                    created_at,
                ),
                "collection_id": collection_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "claim_id": claim_id,
                "review_status": review_status,
                "issue_type": issue_type,
                "note": note,
                "reviewer": reviewer,
                "created_at": created_at,
            }
        )
        return self.evaluation_repository.upsert_research_understanding_feedback(
            feedback
        )

    def list_feedback(
        self,
        *,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingFeedback, ...]:
        return self.evaluation_repository.list_research_understanding_feedback(
            collection_id=collection_id,
            scope_type=scope_type,
            scope_id=scope_id,
            claim_id=claim_id,
        )

    def record_curation(
        self,
        *,
        collection_id: str,
        scope_type: str,
        scope_id: str,
        claim_id: str,
        curated_claim_type: str,
        curated_status: str,
        curated_statement: str,
        curated_evidence_ref_ids: list[str],
        curated_context_ids: list[str],
        note: str | None = None,
        reviewer: str | None = None,
    ) -> ResearchUnderstandingCuration:
        updated_at = _now_iso()
        curation = ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": _curation_id(
                    collection_id,
                    scope_type,
                    scope_id,
                    claim_id,
                ),
                "collection_id": collection_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "claim_id": claim_id,
                "curated_claim_type": curated_claim_type,
                "curated_status": curated_status,
                "curated_statement": curated_statement,
                "curated_evidence_ref_ids": curated_evidence_ref_ids,
                "curated_context_ids": curated_context_ids,
                "note": note,
                "reviewer": reviewer,
                "updated_at": updated_at,
            }
        )
        return self.evaluation_repository.upsert_research_understanding_curation(
            curation
        )

    def list_curations(
        self,
        *,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingCuration, ...]:
        return self.evaluation_repository.list_research_understanding_curations(
            collection_id=collection_id,
            scope_type=scope_type,
            scope_id=scope_id,
            claim_id=claim_id,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _feedback_id(*parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return "ruf_" + sha1(payload.encode("utf-8")).hexdigest()[:16]


def _curation_id(*parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return "ruc_" + sha1(payload.encode("utf-8")).hexdigest()[:16]
