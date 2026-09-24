"""PostgreSQL persistence for feedback analysis results and workbench cases."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.feedback.analysis_result import AnalysisResult
from domain.feedback.annotation import FeedbackAnnotation
from domain.feedback.feedback_case import FeedbackCase
from domain.feedback.review_decision import ReviewDecision
from infra.persistence.postgres.models.feedback import (
    FeedbackAnnotationRow,
    FeedbackAnalysisResultRow,
    FeedbackCaseRow,
    FeedbackReviewDecisionRow,
)


class PostgresFeedbackCaseRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save_analysis_result(self, result: AnalysisResult) -> AnalysisResult:
        async with self.session_factory.begin() as session:
            row = await _save_result_row(session, result)
            await session.flush()
            return _result(row)

    async def upsert_case_from_analysis(
        self,
        result: AnalysisResult,
        *,
        context_snapshot: dict[str, Any],
        source_signal_ids: tuple[str, ...] = (),
        now: str,
    ) -> FeedbackCase:
        timestamp = _datetime(now)
        signals = _ordered_unique(source_signal_ids or (result.feedback_id,))
        async with self.session_factory.begin() as session:
            # Keep this method usable when a caller has not separately persisted
            # the result, while preserving the same result identity and payload.
            await _save_result_row(session, result)
            row = await session.scalar(
                select(FeedbackCaseRow)
                .where(
                    FeedbackCaseRow.session_id == result.session_id,
                    FeedbackCaseRow.anchor_message_id == result.anchor_message_id,
                )
                .with_for_update()
            )
            if row is None:
                row = FeedbackCaseRow(
                    case_id=f"case_{uuid4().hex[:32]}",
                    collection_id=result.collection_id,
                    session_id=result.session_id,
                    anchor_message_id=result.anchor_message_id,
                    source_signal_ids=list(signals),
                    analysis_result_ids=[result.result_id],
                    context_snapshot=deepcopy(context_snapshot),
                    status="needs_annotation",
                    created_at=timestamp,
                    updated_at=timestamp,
                    annotation_digest=None,
                )
                session.add(row)
            else:
                if row.collection_id != result.collection_id:
                    raise ValueError("feedback case identity cannot change collection")
                row.source_signal_ids = list(
                    _ordered_unique(tuple(row.source_signal_ids or ()) + signals)
                )
                row.analysis_result_ids = list(
                    _ordered_unique(
                        tuple(row.analysis_result_ids or ()) + (result.result_id,)
                    )
                )
                if context_snapshot:
                    row.context_snapshot = deepcopy(context_snapshot)
                if row.status not in {"accepted", "withdrawn"}:
                    row.status = "needs_annotation"
                row.updated_at = timestamp
            await session.flush()
            return _case(row)

    async def read_case(self, case_id: str) -> FeedbackCase | None:
        async with self.session_factory() as session:
            row = await session.get(FeedbackCaseRow, case_id)
            return _case(row) if row is not None else None

    async def read_analysis_results(
        self, result_ids: tuple[str, ...]
    ) -> tuple[AnalysisResult, ...]:
        ids = tuple(dict.fromkeys(str(value) for value in result_ids if value))
        if not ids:
            return ()
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(FeedbackAnalysisResultRow).where(
                    FeedbackAnalysisResultRow.result_id.in_(ids)
                )
            )
            by_id = {row.result_id: _result(row) for row in rows}
            return tuple(by_id[value] for value in ids if value in by_id)

    async def list_cases(
        self,
        *,
        collection_id: str | None = None,
        collection_ids: tuple[str, ...] | None = None,
        status: str | None = None,
        problem_type: str | None = None,
        limit: int | None = 50,
        offset: int = 0,
    ) -> tuple[FeedbackCase, ...]:
        if limit is not None and limit < 0 or offset < 0:
            raise ValueError("limit and offset must be non-negative")
        statement = select(FeedbackCaseRow)
        if collection_id is not None:
            statement = statement.where(FeedbackCaseRow.collection_id == collection_id)
        elif collection_ids is not None:
            if not collection_ids:
                return ()
            statement = statement.where(FeedbackCaseRow.collection_id.in_(collection_ids))
        if status is not None:
            statement = statement.where(FeedbackCaseRow.status == status)
        statement = statement.order_by(
            FeedbackCaseRow.created_at,
            FeedbackCaseRow.case_id,
        )
        async with self.session_factory() as session:
            rows = list(await session.scalars(statement))
            if problem_type is not None and rows:
                result_ids = {
                    result_id
                    for row in rows
                    for result_id in (row.analysis_result_ids or ())
                }
                matching_result_ids: set[str] = set()
                if result_ids:
                    result_rows = await session.scalars(
                        select(FeedbackAnalysisResultRow).where(
                            FeedbackAnalysisResultRow.result_id.in_(result_ids),
                        )
                    )
                    by_case_result = {
                        result_row.result_id: result_row for result_row in result_rows
                    }
                    for row in rows:
                        latest = max(
                            (
                                by_case_result[result_id]
                                for result_id in (row.analysis_result_ids or ())
                                if result_id in by_case_result
                            ),
                            key=lambda item: (item.created_at, item.result_id),
                            default=None,
                        )
                        if latest is not None and latest.problem_type == problem_type:
                            matching_result_ids.add(latest.result_id)
                rows = [
                    row
                    for row in rows
                    if any(result_id in matching_result_ids for result_id in (row.analysis_result_ids or ()))
                ]
            rows = rows[offset:] if limit is None else rows[offset : offset + limit]
            return tuple(_case(row) for row in rows)

    async def read_annotation(self, case_id: str) -> FeedbackAnnotation | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(FeedbackAnnotationRow)
                .where(FeedbackAnnotationRow.case_id == case_id)
                .order_by(FeedbackAnnotationRow.version.desc())
                .limit(1)
            )
            return _annotation(row) if row is not None else None

    async def save_annotation(
        self,
        annotation: FeedbackAnnotation,
        *,
        expected_digest: str | None,
        now: str,
    ) -> FeedbackAnnotation:
        timestamp = _datetime(now)
        async with self.session_factory.begin() as session:
            case = await session.scalar(
                select(FeedbackCaseRow)
                .where(FeedbackCaseRow.case_id == annotation.case_id)
                .with_for_update()
            )
            if case is None:
                raise FileNotFoundError(f"feedback case not found: {annotation.case_id}")
            if expected_digest != case.annotation_digest:
                raise ValueError("feedback_case_stale")
            if case.status not in {
                "needs_annotation",
                "ready_for_review",
                "rejected",
                "insufficient",
            }:
                raise ValueError("feedback_case_not_annotatable")
            current = await session.scalar(
                select(FeedbackAnnotationRow)
                .where(FeedbackAnnotationRow.case_id == annotation.case_id)
                .order_by(FeedbackAnnotationRow.version.desc())
                .limit(1)
            )
            if current is not None and current.annotation_digest == annotation.annotation_digest:
                return _annotation(current)
            expected_version = (current.version + 1) if current is not None else 1
            if annotation.version != expected_version:
                raise ValueError("annotation_version_conflict")
            row = FeedbackAnnotationRow(
                annotation_id=annotation.annotation_id,
                case_id=annotation.case_id,
                version=annotation.version,
                problem_type=annotation.problem_type,
                severity=annotation.severity,
                target=annotation.target,
                support_source_refs=list(annotation.support_source_refs),
                dataset_uses=list(annotation.dataset_uses),
                reason=annotation.reason,
                annotation_digest=annotation.annotation_digest,
                created_by=annotation.created_by,
                created_at=_datetime(annotation.created_at),
                updated_at=timestamp,
            )
            session.add(row)
            case.annotation_digest = annotation.annotation_digest
            case.status = "ready_for_review"
            case.updated_at = timestamp
            await session.flush()
            return _annotation(row)

    async def read_review_decisions(self, case_id: str) -> tuple[ReviewDecision, ...]:
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(FeedbackReviewDecisionRow)
                .where(FeedbackReviewDecisionRow.case_id == case_id)
                .order_by(FeedbackReviewDecisionRow.seq)
            )
            return tuple(_review_decision(row) for row in rows)

    async def append_review_decision(
        self,
        decision: ReviewDecision,
        *,
        expected_annotation_digest: str,
        now: str,
    ) -> ReviewDecision:
        timestamp = _datetime(now)
        async with self.session_factory.begin() as session:
            case = await session.scalar(
                select(FeedbackCaseRow)
                .where(FeedbackCaseRow.case_id == decision.case_id)
                .with_for_update()
            )
            if case is None:
                raise FileNotFoundError(f"feedback case not found: {decision.case_id}")
            if case.annotation_digest != expected_annotation_digest:
                raise ValueError("feedback_case_stale")
            if case.annotation_digest != decision.annotation_digest:
                raise ValueError("feedback_case_stale")
            annotation = await session.scalar(
                select(FeedbackAnnotationRow)
                .where(
                    FeedbackAnnotationRow.case_id == decision.case_id,
                    FeedbackAnnotationRow.annotation_digest == decision.annotation_digest,
                )
                .limit(1)
            )
            if annotation is None:
                raise ValueError("feedback_case_annotation_required")
            if decision.decision == "withdraw":
                if case.status != "accepted":
                    raise ValueError("feedback_case_not_withdrawable")
            elif case.status != "ready_for_review":
                raise ValueError("feedback_case_not_reviewable")
            max_seq = await session.scalar(
                select(func.max(FeedbackReviewDecisionRow.seq)).where(
                    FeedbackReviewDecisionRow.case_id == decision.case_id
                )
            )
            actual_seq = int(max_seq or 0) + 1
            if decision.seq != actual_seq:
                decision = replace(decision, seq=actual_seq)
            row = FeedbackReviewDecisionRow(
                decision_id=decision.decision_id,
                case_id=decision.case_id,
                annotation_digest=decision.annotation_digest,
                decision=decision.decision,
                reason=decision.reason,
                created_by=decision.created_by,
                seq=actual_seq,
                created_at=timestamp,
            )
            session.add(row)
            case.status = {
                "accept": "accepted",
                "reject": "rejected",
                "insufficient": "insufficient",
                "withdraw": "withdrawn",
            }[decision.decision]
            case.updated_at = timestamp
            await session.flush()
            return _review_decision(row)


async def _save_result_row(
    session: AsyncSession, result: AnalysisResult
) -> FeedbackAnalysisResultRow:
    row = await session.get(FeedbackAnalysisResultRow, result.result_id)
    by_job = await session.scalar(
        select(FeedbackAnalysisResultRow).where(
            FeedbackAnalysisResultRow.job_id == result.job_id
        )
    )
    if row is not None and row.job_id != result.job_id:
        raise ValueError("analysis result identity cannot be reassigned")
    if by_job is not None and by_job.result_id != result.result_id:
        raise ValueError("analysis job already has another result")
    existing = row or by_job
    if existing is not None:
        identity = (
            existing.job_id,
            existing.feedback_id,
            existing.session_id,
            existing.collection_id,
            existing.anchor_message_id,
        )
        requested_identity = (
            result.job_id,
            result.feedback_id,
            result.session_id,
            result.collection_id,
            result.anchor_message_id,
        )
        if identity != requested_identity:
            raise ValueError("analysis result identity cannot be reassigned")
    if row is None:
        row = by_job or FeedbackAnalysisResultRow(result_id=result.result_id)
        if by_job is None:
            session.add(row)
    row.job_id = result.job_id
    row.feedback_id = result.feedback_id
    row.session_id = result.session_id
    row.collection_id = result.collection_id
    row.anchor_message_id = result.anchor_message_id
    row.problem_type = result.problem_type
    row.confidence = result.confidence
    row.related_message_ids = list(result.related_message_ids)
    row.suggested_evidence = list(result.suggested_evidence)
    row.suggested_target = result.suggested_target
    row.evidence_coverage = result.evidence_coverage.to_record()
    row.model = result.model
    row.input_digest = result.input_digest
    row.created_at = _datetime(result.created_at)
    return row


def _result(row: FeedbackAnalysisResultRow) -> AnalysisResult:
    from domain.feedback.evidence_coverage import EvidenceCoverage

    return AnalysisResult(
        result_id=row.result_id,
        job_id=row.job_id,
        feedback_id=row.feedback_id,
        session_id=row.session_id,
        collection_id=row.collection_id,
        anchor_message_id=row.anchor_message_id,
        problem_type=row.problem_type,
        confidence=float(row.confidence),
        related_message_ids=tuple(row.related_message_ids or ()),
        suggested_evidence=tuple(row.suggested_evidence or ()),
        suggested_target=row.suggested_target,
        evidence_coverage=EvidenceCoverage.from_record(row.evidence_coverage),
        model=row.model,
        input_digest=row.input_digest,
        created_at=_iso(row.created_at),
    )


def _case(row: FeedbackCaseRow) -> FeedbackCase:
    return FeedbackCase(
        case_id=row.case_id,
        collection_id=row.collection_id,
        session_id=row.session_id,
        anchor_message_id=row.anchor_message_id,
        source_signal_ids=tuple(row.source_signal_ids or ()),
        analysis_result_ids=tuple(row.analysis_result_ids or ()),
        context_snapshot=deepcopy(row.context_snapshot or {}),
        status=row.status,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        annotation_digest=row.annotation_digest,
    )


def _annotation(row: FeedbackAnnotationRow) -> FeedbackAnnotation:
    return FeedbackAnnotation(
        annotation_id=row.annotation_id,
        case_id=row.case_id,
        version=row.version,
        problem_type=row.problem_type,
        severity=row.severity,
        target=row.target,
        support_source_refs=tuple(row.support_source_refs or ()),
        dataset_uses=tuple(row.dataset_uses or ()),
        reason=row.reason,
        annotation_digest=row.annotation_digest,
        created_by=row.created_by,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _review_decision(row: FeedbackReviewDecisionRow) -> ReviewDecision:
    return ReviewDecision(
        decision_id=row.decision_id,
        case_id=row.case_id,
        annotation_digest=row.annotation_digest,
        decision=row.decision,
        reason=row.reason,
        created_by=row.created_by,
        seq=row.seq,
        created_at=_iso(row.created_at),
    )


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if value))


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        parsed = datetime.fromisoformat(
            f"{text[:-1]}+00:00" if text.endswith("Z") else text
        )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _datetime(value).isoformat()


__all__ = ["PostgresFeedbackCaseRepository"]
