"""Direct PostgreSQL persistence for Objective Understanding review records."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from domain.evaluation import (
    ResearchUnderstandingCuration,
    ResearchUnderstandingFeedback,
)
from infra.persistence.postgres.models.evaluation import (
    ResearchUnderstandingCurationRecord,
    ResearchUnderstandingFeedbackRecord,
)
from infra.persistence.postgres.models.understanding import (
    ResearchFindingRecord,
    ResearchUnderstandingRecord,
)


class PostgresResearchUnderstandingReviewRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_feedback(
        self,
        feedback: ResearchUnderstandingFeedback,
    ) -> ResearchUnderstandingFeedback:
        with self.session_factory.begin() as session:
            understanding, finding = _review_target(
                session,
                feedback.collection_id,
                feedback.objective_id,
                feedback.finding_id,
                feedback.claim_id,
            )
            existing = session.get(
                ResearchUnderstandingFeedbackRecord, feedback.feedback_id
            )
            if existing is not None and (
                existing.collection_id != feedback.collection_id
                or existing.objective_id != feedback.objective_id
                or existing.finding_id != feedback.finding_id
            ):
                raise ValueError("feedback identity cannot be reassigned")
            row = existing or ResearchUnderstandingFeedbackRecord(
                feedback_id=feedback.feedback_id,
                understanding_id=understanding.understanding_id,
                collection_id=feedback.collection_id,
                objective_id=feedback.objective_id,
                finding_id=feedback.finding_id,
                claim_id=finding.claim_id,
                finding_fingerprint=feedback.finding_fingerprint,
                review_status=feedback.review_status,
                issue_type=feedback.issue_type,
                note=feedback.note,
                reviewer=feedback.reviewer,
                created_at=_datetime(feedback.created_at),
            )
            row.understanding_id = understanding.understanding_id
            row.claim_id = finding.claim_id
            row.finding_fingerprint = feedback.finding_fingerprint
            row.review_status = feedback.review_status
            row.issue_type = feedback.issue_type
            row.note = feedback.note
            row.reviewer = feedback.reviewer
            row.created_at = _datetime(feedback.created_at)
            if existing is None:
                session.add(row)
            session.flush()
            return _feedback(row)

    def list_feedback(
        self,
        collection_id: str,
        objective_id: str | None = None,
        finding_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingFeedback, ...]:
        with self.session_factory() as session:
            statement = select(ResearchUnderstandingFeedbackRecord).where(
                ResearchUnderstandingFeedbackRecord.collection_id == collection_id
            )
            if objective_id is not None:
                statement = statement.where(
                    ResearchUnderstandingFeedbackRecord.objective_id == objective_id
                )
            if finding_id is not None:
                statement = statement.where(
                    ResearchUnderstandingFeedbackRecord.finding_id == finding_id
                )
            if claim_id is not None:
                statement = statement.where(
                    ResearchUnderstandingFeedbackRecord.claim_id == claim_id
                )
            rows = session.scalars(
                statement.order_by(
                    ResearchUnderstandingFeedbackRecord.created_at,
                    ResearchUnderstandingFeedbackRecord.feedback_id,
                )
            )
            return tuple(_feedback(row) for row in rows)

    def upsert_curation(
        self,
        curation: ResearchUnderstandingCuration,
    ) -> ResearchUnderstandingCuration:
        with self.session_factory.begin() as session:
            understanding, finding = _review_target(
                session,
                curation.collection_id,
                curation.objective_id,
                curation.finding_id,
                curation.claim_id,
            )
            existing = session.get(
                ResearchUnderstandingCurationRecord, curation.curation_id
            )
            if existing is not None and (
                existing.collection_id != curation.collection_id
                or existing.objective_id != curation.objective_id
                or existing.finding_id != curation.finding_id
            ):
                raise ValueError("curation identity cannot be reassigned")
            row = existing or ResearchUnderstandingCurationRecord(
                curation_id=curation.curation_id,
                understanding_id=understanding.understanding_id,
                collection_id=curation.collection_id,
                objective_id=curation.objective_id,
                finding_id=curation.finding_id,
                claim_id=finding.claim_id,
                finding_fingerprint=curation.finding_fingerprint,
                curated_claim_type=curation.curated_claim_type,
                curated_status=curation.curated_status,
                curated_statement=curation.curated_statement,
                curated_support_grade=curation.curated_support_grade,
                curated_review_status=curation.curated_review_status,
                curated_variables=list(curation.curated_variables),
                curated_mediators=list(curation.curated_mediators),
                curated_outcomes=list(curation.curated_outcomes),
                curated_direction=curation.curated_direction,
                curated_scope_summary=curation.curated_scope_summary,
                curated_evidence_ref_ids=list(curation.curated_evidence_ref_ids),
                curated_context_ids=list(curation.curated_context_ids),
                note=curation.note,
                reviewer=curation.reviewer,
                updated_at=_datetime(curation.updated_at),
            )
            row.understanding_id = understanding.understanding_id
            row.claim_id = finding.claim_id
            row.finding_fingerprint = curation.finding_fingerprint
            row.curated_claim_type = curation.curated_claim_type
            row.curated_status = curation.curated_status
            row.curated_statement = curation.curated_statement
            row.curated_support_grade = curation.curated_support_grade
            row.curated_review_status = curation.curated_review_status
            row.curated_variables = list(curation.curated_variables)
            row.curated_mediators = list(curation.curated_mediators)
            row.curated_outcomes = list(curation.curated_outcomes)
            row.curated_direction = curation.curated_direction
            row.curated_scope_summary = curation.curated_scope_summary
            row.curated_evidence_ref_ids = list(curation.curated_evidence_ref_ids)
            row.curated_context_ids = list(curation.curated_context_ids)
            row.note = curation.note
            row.reviewer = curation.reviewer
            row.updated_at = _datetime(curation.updated_at)
            if existing is None:
                session.add(row)
            session.flush()
            return _curation(row)

    def list_curations(
        self,
        collection_id: str,
        objective_id: str | None = None,
        finding_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingCuration, ...]:
        with self.session_factory() as session:
            statement = select(ResearchUnderstandingCurationRecord).where(
                ResearchUnderstandingCurationRecord.collection_id == collection_id
            )
            if objective_id is not None:
                statement = statement.where(
                    ResearchUnderstandingCurationRecord.objective_id == objective_id
                )
            if finding_id is not None:
                statement = statement.where(
                    ResearchUnderstandingCurationRecord.finding_id == finding_id
                )
            if claim_id is not None:
                statement = statement.where(
                    ResearchUnderstandingCurationRecord.claim_id == claim_id
                )
            rows = session.scalars(
                statement.order_by(
                    ResearchUnderstandingCurationRecord.updated_at,
                    ResearchUnderstandingCurationRecord.curation_id,
                )
            )
            return tuple(_curation(row) for row in rows)


def _review_target(
    session: Session,
    collection_id: str,
    objective_id: str,
    finding_id: str,
    claim_id: str | None,
) -> tuple[ResearchUnderstandingRecord, ResearchFindingRecord]:
    understanding = session.scalar(
        select(ResearchUnderstandingRecord).where(
            ResearchUnderstandingRecord.collection_id == collection_id,
            ResearchUnderstandingRecord.objective_id == objective_id,
        )
    )
    if understanding is None:
        raise ValueError(
            f"Research Understanding not found: {collection_id}/{objective_id}"
        )
    finding = session.get(
        ResearchFindingRecord,
        {
            "understanding_id": understanding.understanding_id,
            "finding_id": finding_id,
        },
    )
    if finding is None:
        raise ValueError(f"Finding not found in Objective Understanding: {finding_id}")
    if claim_id is not None and claim_id != finding.claim_id:
        raise ValueError("Finding and claim do not belong to the same Objective")
    return understanding, finding


def _feedback(
    row: ResearchUnderstandingFeedbackRecord,
) -> ResearchUnderstandingFeedback:
    return ResearchUnderstandingFeedback.from_mapping(
        {
            "feedback_id": row.feedback_id,
            "collection_id": row.collection_id,
            "objective_id": row.objective_id,
            "finding_id": row.finding_id,
            "claim_id": row.claim_id,
            "finding_fingerprint": row.finding_fingerprint,
            "review_status": row.review_status,
            "issue_type": row.issue_type,
            "note": row.note,
            "reviewer": row.reviewer,
            "created_at": _isoformat(row.created_at),
        }
    )


def _curation(
    row: ResearchUnderstandingCurationRecord,
) -> ResearchUnderstandingCuration:
    return ResearchUnderstandingCuration.from_mapping(
        {
            "curation_id": row.curation_id,
            "collection_id": row.collection_id,
            "objective_id": row.objective_id,
            "finding_id": row.finding_id,
            "claim_id": row.claim_id,
            "finding_fingerprint": row.finding_fingerprint,
            "curated_claim_type": row.curated_claim_type,
            "curated_status": row.curated_status,
            "curated_statement": row.curated_statement,
            "curated_support_grade": row.curated_support_grade,
            "curated_review_status": row.curated_review_status,
            "curated_variables": list(row.curated_variables),
            "curated_mediators": list(row.curated_mediators),
            "curated_outcomes": list(row.curated_outcomes),
            "curated_direction": row.curated_direction,
            "curated_scope_summary": row.curated_scope_summary,
            "curated_evidence_ref_ids": list(row.curated_evidence_ref_ids),
            "curated_context_ids": list(row.curated_context_ids),
            "note": row.note,
            "reviewer": row.reviewer,
            "updated_at": _isoformat(row.updated_at),
        }
    )


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


__all__ = ["PostgresResearchUnderstandingReviewRepository"]
