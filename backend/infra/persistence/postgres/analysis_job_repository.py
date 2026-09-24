"""PostgreSQL persistence and atomic claiming for analysis jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.feedback.analysis_job import AnalysisJob
from domain.feedback.correction_signal import (
    CORRECTION_SIGNAL_JOB_TYPE,
    CORRECTION_SIGNAL_PAYLOAD_VERSION,
    correction_signal_idempotency_key,
)
from infra.persistence.postgres.models.feedback import AnalysisJobRow


class PostgresAnalysisJobRepository:
    """Store versioned job envelopes without exposing ORM rows to callers."""

    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def enqueue_feedback_analysis(
        self,
        feedback_id: str,
        idempotency_key: str,
        now: str,
    ) -> AnalysisJob:
        if not feedback_id.strip():
            raise ValueError("feedback_id is required")
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        timestamp = _datetime(now)
        try:
            async with self.session_factory.begin() as session:
                existing = await session.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    _ensure_feedback_identity(existing, feedback_id)
                    return _job(existing)
                row = AnalysisJobRow(
                    job_id=f"job_{uuid4().hex[:32]}",
                    job_type="feedback_analysis",
                    payload_version=1,
                    payload={"feedback_id": feedback_id},
                    status="pending",
                    available_at=timestamp,
                    started_at=None,
                    finished_at=None,
                    result_id=None,
                    error_code=None,
                    idempotency_key=idempotency_key,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                await session.flush()
                return _job(row)
        except IntegrityError:
            # A concurrent producer may have won the unique idempotency key.
            async with self.session_factory() as session:
                existing = await session.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                _ensure_feedback_identity(existing, feedback_id)
                return _job(existing)

    async def enqueue_correction_signal_analysis(
        self,
        *,
        session_id: str,
        anchor_message_id: str,
        trigger_message_id: str,
        trigger_digest: str,
        idempotency_key: str,
        now: str,
    ) -> AnalysisJob:
        """Queue one immutable message-derived candidate in the shared envelope."""

        values = tuple(
            str(value or "").strip()
            for value in (
                session_id,
                anchor_message_id,
                trigger_message_id,
                trigger_digest,
                idempotency_key,
            )
        )
        if any(not value for value in values):
            raise ValueError("correction signal job identity is required")
        expected_key = correction_signal_idempotency_key(
            session_id=session_id,
            anchor_message_id=anchor_message_id,
            trigger_message_id=trigger_message_id,
            trigger_digest=trigger_digest,
        )
        if idempotency_key != expected_key:
            raise ValueError("correction signal idempotency key does not match payload")
        timestamp = _datetime(now)
        payload = {
            "session_id": session_id,
            "anchor_message_id": anchor_message_id,
            "trigger_message_id": trigger_message_id,
            "trigger_digest": trigger_digest,
        }
        try:
            async with self.session_factory.begin() as session:
                existing = await session.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    _ensure_correction_identity(existing, payload)
                    return _job(existing)
                row = AnalysisJobRow(
                    job_id=f"job_{uuid4().hex[:32]}",
                    job_type=CORRECTION_SIGNAL_JOB_TYPE,
                    payload_version=CORRECTION_SIGNAL_PAYLOAD_VERSION,
                    payload=payload,
                    status="pending",
                    available_at=timestamp,
                    started_at=None,
                    finished_at=None,
                    result_id=None,
                    error_code=None,
                    idempotency_key=idempotency_key,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                await session.flush()
                return _job(row)
        except IntegrityError:
            async with self.session_factory() as session:
                existing = await session.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                _ensure_correction_identity(existing, payload)
                return _job(existing)

    async def claim_next_feedback_analysis_job(self, now: str) -> AnalysisJob | None:
        timestamp = _datetime(now)
        async with self.session_factory.begin() as session:
            row = await session.scalar(
                select(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_type == "feedback_analysis",
                    AnalysisJobRow.status == "pending",
                    AnalysisJobRow.available_at <= timestamp,
                )
                .order_by(
                    AnalysisJobRow.available_at,
                    AnalysisJobRow.created_at,
                    AnalysisJobRow.job_id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = "running"
            row.started_at = timestamp
            row.updated_at = timestamp
            await session.flush()
            return _job(row)

    async def claim_next_correction_signal_analysis_job(
        self, now: str
    ) -> AnalysisJob | None:
        timestamp = _datetime(now)
        async with self.session_factory.begin() as session:
            row = await session.scalar(
                select(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_type == CORRECTION_SIGNAL_JOB_TYPE,
                    AnalysisJobRow.status == "pending",
                    AnalysisJobRow.available_at <= timestamp,
                )
                .order_by(
                    AnalysisJobRow.available_at,
                    AnalysisJobRow.created_at,
                    AnalysisJobRow.job_id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = "running"
            row.started_at = timestamp
            row.updated_at = timestamp
            await session.flush()
            return _job(row)

    async def mark_succeeded(
        self,
        job_id: str,
        result_id: str,
        finished_at: str,
    ) -> AnalysisJob:
        return await self._mark_finished(
            job_id=job_id,
            status="succeeded",
            finished_at=finished_at,
            result_id=result_id,
            error_code=None,
        )

    async def mark_failed(
        self,
        job_id: str,
        error_code: str,
        finished_at: str,
    ) -> AnalysisJob:
        return await self._mark_finished(
            job_id=job_id,
            status="failed",
            finished_at=finished_at,
            result_id=None,
            error_code=error_code,
        )

    async def mark_cancelled(
        self,
        job_id: str,
        error_code: str,
        finished_at: str,
    ) -> AnalysisJob:
        return await self._mark_finished(
            job_id=job_id,
            status="cancelled",
            finished_at=finished_at,
            result_id=None,
            error_code=error_code,
        )

    async def requeue_failed_feedback_analysis_job(
        self,
        job_id: str,
        now: str,
    ) -> AnalysisJob:
        """Atomically return one failed feedback-analysis job to ``pending``.

        This is deliberately a manual operation.  The row lock prevents a
        worker or another operator from changing the terminal state between
        validation and the reset of the execution fields.
        """
        if not job_id.strip():
            raise ValueError("job_id is required")
        timestamp = _datetime(now)
        available_at = _iso(timestamp)
        async with self.session_factory.begin() as session:
            row = await session.get(AnalysisJobRow, job_id, with_for_update=True)
            if row is None:
                raise FileNotFoundError(f"analysis job not found: {job_id}")
            if row.job_type != "feedback_analysis":
                raise ValueError("only feedback analysis jobs can be requeued")
            if row.status != "failed":
                raise ValueError(f"cannot requeue analysis job in status {row.status}")
            if row.result_id is not None:
                raise ValueError("failed analysis job with a result cannot be requeued")

            requeued = _job(row).requeue_failed_feedback_analysis(available_at)
            row.status = requeued.status
            row.available_at = timestamp
            row.started_at = None
            row.finished_at = None
            row.result_id = None
            row.error_code = None
            row.updated_at = timestamp
            await session.flush()
            return _job(row)

    async def cancel_feedback_analysis_jobs(
        self,
        feedback_id: str,
        finished_at: str,
    ) -> int:
        """Cancel pending jobs for one withdrawn persisted feedback version.

        The job envelope deliberately stores only a type-specific payload, so
        cancellation matches its ``feedback_id`` rather than inventing shared
        session/message columns. Running jobs are left to their handler, which
        re-reads the feedback and records ``feedback_withdrawn`` if it has
        disappeared.
        """
        if not feedback_id.strip():
            raise ValueError("feedback_id is required")
        timestamp = _datetime(finished_at)
        cancelled = 0
        async with self.session_factory.begin() as session:
            rows = await session.scalars(
                select(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_type == "feedback_analysis",
                    AnalysisJobRow.status == "pending",
                )
                .with_for_update()
            )
            for row in rows:
                payload = row.payload or {}
                if payload.get("feedback_id") != feedback_id:
                    continue
                row.status = "cancelled"
                row.finished_at = timestamp
                row.updated_at = timestamp
                row.error_code = "feedback_withdrawn"
                cancelled += 1
            await session.flush()
        return cancelled

    async def cancel_correction_signal_analysis_jobs(
        self, *, trigger_message_id: str, finished_at: str
    ) -> int:
        """Cancel pending candidates whose immutable trigger was withdrawn."""

        trigger = str(trigger_message_id or "").strip()
        if not trigger:
            raise ValueError("trigger_message_id is required")
        timestamp = _datetime(finished_at)
        cancelled = 0
        async with self.session_factory.begin() as session:
            rows = await session.scalars(
                select(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_type == CORRECTION_SIGNAL_JOB_TYPE,
                    AnalysisJobRow.status == "pending",
                )
                .with_for_update()
            )
            for row in rows:
                if (row.payload or {}).get("trigger_message_id") != trigger:
                    continue
                row.status = "cancelled"
                row.finished_at = timestamp
                row.updated_at = timestamp
                row.error_code = "correction_signal_withdrawn"
                cancelled += 1
            await session.flush()
        return cancelled

    async def _mark_finished(
        self,
        *,
        job_id: str,
        status: str,
        finished_at: str,
        result_id: str | None,
        error_code: str | None,
    ) -> AnalysisJob:
        timestamp = _datetime(finished_at)
        async with self.session_factory.begin() as session:
            row = await session.get(AnalysisJobRow, job_id, with_for_update=True)
            if row is None:
                raise FileNotFoundError(f"analysis job not found: {job_id}")
            if row.status in {"succeeded", "failed", "cancelled"}:
                if (
                    row.status != status
                    or row.result_id != result_id
                    or row.error_code != error_code
                ):
                    raise ValueError("analysis job is already in a different terminal state")
                return _job(row)
            if row.status not in {"pending", "running"}:
                raise ValueError(f"analysis job cannot finish from {row.status}")
            row.status = status
            row.finished_at = timestamp
            row.updated_at = timestamp
            row.result_id = result_id
            row.error_code = error_code
            await session.flush()
            return _job(row)

    async def read_job(self, job_id: str) -> AnalysisJob | None:
        async with self.session_factory() as session:
            row = await session.get(AnalysisJobRow, job_id)
            return _job(row) if row is not None else None

    async def list_jobs(
        self,
        *,
        job_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[AnalysisJob, ...]:
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must be non-negative")
        statement = select(AnalysisJobRow)
        if job_type is not None:
            statement = statement.where(AnalysisJobRow.job_type == job_type)
        if status is not None:
            statement = statement.where(AnalysisJobRow.status == status)
        statement = statement.order_by(
            AnalysisJobRow.created_at,
            AnalysisJobRow.job_id,
        ).offset(offset).limit(limit)
        async with self.session_factory() as session:
            rows = await session.scalars(statement)
            return tuple(_job(row) for row in rows)


def _ensure_feedback_identity(row: AnalysisJobRow, feedback_id: str) -> None:
    payload = row.payload or {}
    if row.job_type != "feedback_analysis" or payload.get("feedback_id") != feedback_id:
        raise ValueError("idempotency key is already bound to another analysis input")


def _ensure_correction_identity(
    row: AnalysisJobRow, payload: dict[str, str]
) -> None:
    if row.job_type != CORRECTION_SIGNAL_JOB_TYPE or dict(row.payload or {}) != payload:
        raise ValueError("idempotency key is already bound to another analysis input")


def _job(row: AnalysisJobRow) -> AnalysisJob:
    return AnalysisJob(
        job_id=row.job_id,
        job_type=row.job_type,
        payload_version=row.payload_version,
        payload=dict(row.payload or {}),
        status=row.status,
        idempotency_key=row.idempotency_key,
        available_at=_iso(row.available_at),
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        started_at=_optional_iso(row.started_at),
        finished_at=_optional_iso(row.finished_at),
        result_id=row.result_id,
        error_code=row.error_code,
    )


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


def _optional_iso(value: datetime | None) -> str | None:
    return _iso(value) if value is not None else None


__all__ = ["PostgresAnalysisJobRepository"]
