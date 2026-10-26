"""PostgreSQL repository for finding review."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core.finding import Finding
from domain.evaluation.records import (
    FindingCuration,
    FindingFeedback,
    _normalize_mapping,
    _normalize_text,
)
from infra.persistence.postgres.models.evaluation import (
    FindingCurationRecord,
    FindingFeedbackRecord,
)
from infra.persistence.postgres.models.experiment_finding import ExperimentFindingRow
from infra.persistence.postgres.models.objective import ObjectiveAnalysisRecord


class FindingReviewRepository:
    backend_name = "postgresql"

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.session_factory = session_factory

    async def upsert_feedback(
        self, feedback: FindingFeedback
    ) -> FindingFeedback:
        async with self.session_factory.begin() as session:
            await _require_finding(session, feedback)
            existing = await session.get(
                FindingFeedbackRecord, feedback.feedback_id
            )
            if existing is not None and _feedback_key(existing) != _feedback_key(
                feedback
            ):
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
            await session.flush()
            return _feedback(row)

    async def list_feedback(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingFeedback, ...]:
        async with self.session_factory() as session:
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
            rows = await session.scalars(
                statement.order_by(
                    FindingFeedbackRecord.created_at,
                    FindingFeedbackRecord.feedback_id,
                )
            )
            return tuple(_feedback(row) for row in rows)

    async def upsert_curation(
        self, curation: FindingCuration
    ) -> FindingCuration:
        async with self.session_factory.begin() as session:
            await _require_finding(session, curation)
            existing = await session.get(
                FindingCurationRecord, curation.curation_id
            )
            if existing is not None and _curation_key(existing) != _curation_key(
                curation
            ):
                raise ValueError("curation identity cannot be reassigned")
            row = existing or FindingCurationRecord(curation_id=curation.curation_id)
            row.collection_id = curation.collection_id
            row.objective_id = curation.objective_id
            row.analysis_version = curation.analysis_version
            row.finding_id = curation.finding_id
            row.curated_status = curation.curated_status
            row.curated_finding = curation.curated_finding.to_record()
            row.note = curation.note
            row.reviewer = curation.reviewer
            row.updated_at = _datetime(curation.updated_at)
            if existing is None:
                session.add(row)
            await session.flush()
            return _curation(row)

    async def list_curations(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingCuration, ...]:
        async with self.session_factory() as session:
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
            rows = await session.scalars(
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
    return finding_feedback_from_record(
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
    return finding_curation_from_record(
        {
            "curation_id": row.curation_id,
            "collection_id": row.collection_id,
            "objective_id": row.objective_id,
            "analysis_version": row.analysis_version,
            "finding_id": row.finding_id,
            "curated_status": row.curated_status,
            "curated_finding": dict(row.curated_finding),
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


async def _require_finding(session: AsyncSession, value: object) -> None:
    row = await session.get(
        ObjectiveAnalysisRecord,
        (
            value.collection_id,
            value.objective_id,
            value.analysis_version,
        ),
    )
    authored_finding = row is not None and any(
        item.get("finding_id") == value.finding_id
        for item in (row.payload or {}).get("findings", ())
    )
    experiment_finding = await session.scalar(
        select(ExperimentFindingRow).where(
            ExperimentFindingRow.collection_id == value.collection_id,
            ExperimentFindingRow.objective_id == value.objective_id,
            ExperimentFindingRow.analysis_version == value.analysis_version,
            ExperimentFindingRow.finding_id == value.finding_id,
        )
    )
    if row is None or (not authored_finding and experiment_finding is None):
        raise ValueError(
            "finding does not exist in the requested objective analysis: "
            f"{value.collection_id}/{value.objective_id}/"
            f"{value.analysis_version}/{value.finding_id}"
        )


__all__ = ['FindingReviewRepository']


def finding_feedback_from_record(payload: Mapping[str, Any]) -> FindingFeedback:
    return FindingFeedback(
        feedback_id=_normalize_text(payload.get("feedback_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        objective_id=_normalize_text(payload.get("objective_id")) or "",
        analysis_version=int(payload.get("analysis_version") or 0),
        finding_id=_normalize_text(payload.get("finding_id")) or "",
        review_status=(_normalize_text(payload.get("review_status")) or "").lower(),
        issue_type=(_normalize_text(payload.get("issue_type")) or "").lower(),
        note=_normalize_text(payload.get("note")), reviewer=_normalize_text(payload.get("reviewer")),
        created_at=_normalize_text(payload.get("created_at")) or "",
    )


def finding_feedback_record(value: FindingFeedback) -> dict[str, Any]:
    return {"feedback_id": value.feedback_id, "collection_id": value.collection_id,
            "objective_id": value.objective_id, "analysis_version": value.analysis_version,
            "finding_id": value.finding_id, "review_status": value.review_status,
            "issue_type": value.issue_type, "note": value.note, "reviewer": value.reviewer,
            "created_at": value.created_at}


def finding_curation_from_record(payload: Mapping[str, Any]) -> FindingCuration:
    return FindingCuration(
        curation_id=_normalize_text(payload.get("curation_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        objective_id=_normalize_text(payload.get("objective_id")) or "",
        analysis_version=int(payload.get("analysis_version") or 0),
        finding_id=_normalize_text(payload.get("finding_id")) or "",
        curated_status=(_normalize_text(payload.get("curated_status")) or "").lower(),
        curated_finding=Finding.from_mapping(_normalize_mapping(payload.get("curated_finding"))),
        note=_normalize_text(payload.get("note")), reviewer=_normalize_text(payload.get("reviewer")),
        updated_at=_normalize_text(payload.get("updated_at")) or "",
    )


def finding_curation_record(value: FindingCuration) -> dict[str, Any]:
    return {"curation_id": value.curation_id, "collection_id": value.collection_id,
            "objective_id": value.objective_id, "analysis_version": value.analysis_version,
            "finding_id": value.finding_id, "curated_status": value.curated_status,
            "curated_finding": value.curated_finding.to_record(), "note": value.note,
            "reviewer": value.reviewer, "updated_at": value.updated_at}
