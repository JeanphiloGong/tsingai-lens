"""Direct PostgreSQL persistence for versioned Finding review records."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from domain.evaluation import FindingCuration, FindingFeedback
from infra.persistence.postgres.models.evaluation import (
    FindingCurationRecord,
    FindingFeedbackRecord,
)


class PostgresFindingReviewRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_feedback(self, feedback: FindingFeedback) -> FindingFeedback:
        with self.session_factory.begin() as session:
            existing = session.get(FindingFeedbackRecord, feedback.feedback_id)
            if existing is not None and _feedback_key(existing) != _feedback_key(feedback):
                raise ValueError("feedback identity cannot be reassigned")
            row = existing or FindingFeedbackRecord(feedback_id=feedback.feedback_id)
            row.collection_id = feedback.collection_id
            row.objective_id = feedback.objective_id
            row.analysis_version = feedback.analysis_version
            row.finding_id = feedback.finding_id
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
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingFeedback, ...]:
        with self.session_factory() as session:
            statement = select(FindingFeedbackRecord).where(
                FindingFeedbackRecord.collection_id == collection_id
            )
            if objective_id is not None:
                statement = statement.where(
                    FindingFeedbackRecord.objective_id == objective_id
                )
            if analysis_version is not None:
                statement = statement.where(
                    FindingFeedbackRecord.analysis_version == analysis_version
                )
            if finding_id is not None:
                statement = statement.where(
                    FindingFeedbackRecord.finding_id == finding_id
                )
            rows = session.scalars(
                statement.order_by(
                    FindingFeedbackRecord.created_at,
                    FindingFeedbackRecord.feedback_id,
                )
            )
            return tuple(_feedback(row) for row in rows)

    def upsert_curation(self, curation: FindingCuration) -> FindingCuration:
        with self.session_factory.begin() as session:
            existing = session.get(FindingCurationRecord, curation.curation_id)
            if existing is not None and _curation_key(existing) != _curation_key(curation):
                raise ValueError("curation identity cannot be reassigned")
            row = existing or FindingCurationRecord(curation_id=curation.curation_id)
            row.collection_id = curation.collection_id
            row.objective_id = curation.objective_id
            row.analysis_version = curation.analysis_version
            row.finding_id = curation.finding_id
            row.curated_status = curation.curated_status
            row.curated_statement = curation.curated_statement
            row.curated_support_grade = curation.curated_support_grade
            row.curated_review_status = curation.curated_review_status
            row.curated_variables = list(curation.curated_variables)
            row.curated_mediators = list(curation.curated_mediators)
            row.curated_outcomes = list(curation.curated_outcomes)
            row.curated_direction = curation.curated_direction
            row.curated_scope_summary = curation.curated_scope_summary
            row.curated_evidence_ids = list(curation.curated_evidence_ids)
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
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingCuration, ...]:
        with self.session_factory() as session:
            statement = select(FindingCurationRecord).where(
                FindingCurationRecord.collection_id == collection_id
            )
            if objective_id is not None:
                statement = statement.where(
                    FindingCurationRecord.objective_id == objective_id
                )
            if analysis_version is not None:
                statement = statement.where(
                    FindingCurationRecord.analysis_version == analysis_version
                )
            if finding_id is not None:
                statement = statement.where(
                    FindingCurationRecord.finding_id == finding_id
                )
            rows = session.scalars(
                statement.order_by(
                    FindingCurationRecord.updated_at,
                    FindingCurationRecord.curation_id,
                )
            )
            return tuple(_curation(row) for row in rows)


def _feedback_key(value) -> tuple[str, str, int, str]:
    return (
        value.collection_id,
        value.objective_id,
        value.analysis_version,
        value.finding_id,
    )


def _curation_key(value) -> tuple[str, str, int, str]:
    return (
        value.collection_id,
        value.objective_id,
        value.analysis_version,
        value.finding_id,
    )


def _feedback(row: FindingFeedbackRecord) -> FindingFeedback:
    return FindingFeedback.from_mapping(
        {
            "feedback_id": row.feedback_id,
            "collection_id": row.collection_id,
            "objective_id": row.objective_id,
            "analysis_version": row.analysis_version,
            "finding_id": row.finding_id,
            "review_status": row.review_status,
            "issue_type": row.issue_type,
            "note": row.note,
            "reviewer": row.reviewer,
            "created_at": _isoformat(row.created_at),
        }
    )


def _curation(row: FindingCurationRecord) -> FindingCuration:
    return FindingCuration.from_mapping(
        {
            "curation_id": row.curation_id,
            "collection_id": row.collection_id,
            "objective_id": row.objective_id,
            "analysis_version": row.analysis_version,
            "finding_id": row.finding_id,
            "curated_status": row.curated_status,
            "curated_statement": row.curated_statement,
            "curated_support_grade": row.curated_support_grade,
            "curated_review_status": row.curated_review_status,
            "curated_variables": list(row.curated_variables),
            "curated_mediators": list(row.curated_mediators),
            "curated_outcomes": list(row.curated_outcomes),
            "curated_direction": row.curated_direction,
            "curated_scope_summary": row.curated_scope_summary,
            "curated_evidence_ids": list(row.curated_evidence_ids),
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


__all__ = ["PostgresFindingReviewRepository"]
