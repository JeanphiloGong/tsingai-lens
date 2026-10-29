"""PostgreSQL repository for analysis job."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from infra.persistence.database import AsyncSessionLocal

from infra.persistence.postgres.models.feedback import AnalysisJobRow
from infra.persistence.postgres.models.feedback_dataset import FeedbackDatasetSampleRow

DATASET_SAMPLE_BUILD_JOB_TYPE = "dataset_sample_build"
DATASET_SAMPLE_BUILD_PAYLOAD_VERSION = 1

CORRECTION_SIGNAL_JOB_TYPE = "correction_signal_analysis"

CORRECTION_SIGNAL_PAYLOAD_VERSION = 1

TOOL_FAILURE_JOB_TYPE = "tool_failure_analysis"

TOOL_FAILURE_PAYLOAD_VERSION = 1


def correction_signal_idempotency_key(
    *,
    session_id: str,
    anchor_message_id: str,
    trigger_message_id: str,
    trigger_digest: str,
) -> str:
    """Return a bounded immutable job identity for a candidate input.

    Chat/session IDs are allowed to be 128 characters each, while the shared
    analysis envelope stores idempotency keys in a 255-character column.  Keep
    the complete identity in the JSON payload and use a digest for the unique
    key so no valid message identity can overflow that column.
    """

    values = tuple(
        str(value or "").strip()
        for value in (session_id, anchor_message_id, trigger_message_id, trigger_digest)
    )
    if any(not value for value in values):
        raise ValueError("correction signal identity is incomplete")
    canonical = "\x1f".join(values).encode("utf-8")
    return "correction-signal:" + sha256(canonical).hexdigest()


def tool_failure_idempotency_key(
    *,
    session_id: str,
    tool_call_id: str,
    assistant_message_id: str,
    result_message_id: str,
    result_digest: str,
) -> str:
    """Return a bounded key for one immutable tool failure observation."""

    values = (session_id, tool_call_id, assistant_message_id, result_message_id, result_digest)
    if any(not value for value in values):
        raise ValueError("tool failure identity is incomplete")
    return "tool-failure:" + sha256("\x1f".join(values).encode("utf-8")).hexdigest()


AnalysisJobStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True)
class AnalysisJob:
    """Execution snapshot returned by the job repository, not a domain entity."""

    job_id: str
    job_type: str
    payload_version: int
    payload: dict[str, Any]
    status: AnalysisJobStatus
    idempotency_key: str
    available_at: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result_id: str | None = None
    error_code: str | None = None
    worker_id: str | None = None
    lease_expires_at: str | None = None
    heartbeat_at: str | None = None
    lease_version: int = 0

    def __post_init__(self) -> None:
        if not self.job_id or not self.job_type:
            raise ValueError("analysis job identity is required")
        if self.payload_version < 1:
            raise ValueError("analysis job payload version must be positive")
        if self.lease_version < 0:
            raise ValueError("analysis job lease version must be non-negative")
        if not self.idempotency_key:
            raise ValueError("analysis job idempotency key is required")
        if (
            self.status in {"succeeded", "failed", "cancelled"}
            and self.finished_at is None
        ):
            raise ValueError("terminal analysis jobs require finished_at")

    @property
    def feedback_id(self) -> str | None:
        return self.payload.get("feedback_id")

    def requeue_failed_feedback_analysis(self, available_at: str) -> "AnalysisJob":
        if self.job_type != "feedback_analysis":
            raise ValueError("only feedback analysis jobs can be requeued")
        if self.status != "failed":
            raise ValueError(f"cannot requeue analysis job in status {self.status}")
        if self.result_id is not None:
            raise ValueError("failed analysis job with a result cannot be requeued")
        if not available_at:
            raise ValueError("available_at is required")
        return replace(
            self,
            status="pending",
            available_at=available_at,
            started_at=None,
            finished_at=None,
            result_id=None,
            error_code=None,
            updated_at=available_at,
        )


class AnalysisJobRepository:
    """Store versioned job envelopes without exposing ORM rows to callers."""

    backend_name = "postgresql"

    lease_seconds = 900

    def __init__(
        self,
        worker_id: str | None = None,
    ) -> None:
        self.worker_id = (worker_id or f"{socket.gethostname()}:{os.getpid()}")[:100]

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
            async with AsyncSessionLocal() as db, db.begin():
                existing = await db.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    _ensure_feedback_identity(existing, feedback_id)
                    return AnalysisJob(
                        job_id=existing.job_id,
                        job_type=existing.job_type,
                        payload_version=existing.payload_version,
                        payload=existing.payload,
                        status=existing.status,
                        idempotency_key=existing.idempotency_key,
                        available_at=_iso(existing.available_at),
                        created_at=_iso(existing.created_at),
                        updated_at=_iso(existing.updated_at),
                        started_at=_optional_iso(existing.started_at),
                        finished_at=_optional_iso(existing.finished_at),
                        result_id=existing.result_id,
                        error_code=existing.error_code,
                        worker_id=existing.worker_id,
                        lease_expires_at=_optional_iso(existing.lease_expires_at),
                        heartbeat_at=_optional_iso(existing.heartbeat_at),
                        lease_version=existing.lease_version,
                    )
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
                db.add(row)
                await db.flush()
                return AnalysisJob(
                    job_id=row.job_id,
                    job_type=row.job_type,
                    payload_version=row.payload_version,
                    payload=row.payload,
                    status=row.status,
                    idempotency_key=row.idempotency_key,
                    available_at=_iso(row.available_at),
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    started_at=_optional_iso(row.started_at),
                    finished_at=_optional_iso(row.finished_at),
                    result_id=row.result_id,
                    error_code=row.error_code,
                    worker_id=row.worker_id,
                    lease_expires_at=_optional_iso(row.lease_expires_at),
                    heartbeat_at=_optional_iso(row.heartbeat_at),
                    lease_version=row.lease_version,
                )
        except IntegrityError:
            # A concurrent producer may have won the unique idempotency key.
            async with AsyncSessionLocal() as db:
                existing = await db.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                _ensure_feedback_identity(existing, feedback_id)
                return AnalysisJob(
                    job_id=existing.job_id,
                    job_type=existing.job_type,
                    payload_version=existing.payload_version,
                    payload=existing.payload,
                    status=existing.status,
                    idempotency_key=existing.idempotency_key,
                    available_at=_iso(existing.available_at),
                    created_at=_iso(existing.created_at),
                    updated_at=_iso(existing.updated_at),
                    started_at=_optional_iso(existing.started_at),
                    finished_at=_optional_iso(existing.finished_at),
                    result_id=existing.result_id,
                    error_code=existing.error_code,
                    worker_id=existing.worker_id,
                    lease_expires_at=_optional_iso(existing.lease_expires_at),
                    heartbeat_at=_optional_iso(existing.heartbeat_at),
                    lease_version=existing.lease_version,
                )

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
            async with AsyncSessionLocal() as db, db.begin():
                existing = await db.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    _ensure_correction_identity(existing, payload)
                    return AnalysisJob(
                        job_id=existing.job_id,
                        job_type=existing.job_type,
                        payload_version=existing.payload_version,
                        payload=existing.payload,
                        status=existing.status,
                        idempotency_key=existing.idempotency_key,
                        available_at=_iso(existing.available_at),
                        created_at=_iso(existing.created_at),
                        updated_at=_iso(existing.updated_at),
                        started_at=_optional_iso(existing.started_at),
                        finished_at=_optional_iso(existing.finished_at),
                        result_id=existing.result_id,
                        error_code=existing.error_code,
                        worker_id=existing.worker_id,
                        lease_expires_at=_optional_iso(existing.lease_expires_at),
                        heartbeat_at=_optional_iso(existing.heartbeat_at),
                        lease_version=existing.lease_version,
                    )
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
                db.add(row)
                await db.flush()
                return AnalysisJob(
                    job_id=row.job_id,
                    job_type=row.job_type,
                    payload_version=row.payload_version,
                    payload=row.payload,
                    status=row.status,
                    idempotency_key=row.idempotency_key,
                    available_at=_iso(row.available_at),
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    started_at=_optional_iso(row.started_at),
                    finished_at=_optional_iso(row.finished_at),
                    result_id=row.result_id,
                    error_code=row.error_code,
                    worker_id=row.worker_id,
                    lease_expires_at=_optional_iso(row.lease_expires_at),
                    heartbeat_at=_optional_iso(row.heartbeat_at),
                    lease_version=row.lease_version,
                )
        except IntegrityError:
            async with AsyncSessionLocal() as db:
                existing = await db.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                _ensure_correction_identity(existing, payload)
                return AnalysisJob(
                    job_id=existing.job_id,
                    job_type=existing.job_type,
                    payload_version=existing.payload_version,
                    payload=existing.payload,
                    status=existing.status,
                    idempotency_key=existing.idempotency_key,
                    available_at=_iso(existing.available_at),
                    created_at=_iso(existing.created_at),
                    updated_at=_iso(existing.updated_at),
                    started_at=_optional_iso(existing.started_at),
                    finished_at=_optional_iso(existing.finished_at),
                    result_id=existing.result_id,
                    error_code=existing.error_code,
                    worker_id=existing.worker_id,
                    lease_expires_at=_optional_iso(existing.lease_expires_at),
                    heartbeat_at=_optional_iso(existing.heartbeat_at),
                    lease_version=existing.lease_version,
                )

    async def enqueue_tool_failure_analysis(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        assistant_message_id: str,
        result_message_id: str,
        result_digest: str,
        idempotency_key: str,
        now: str,
    ) -> AnalysisJob:
        """Queue one immutable failed tool result for isolated analysis."""

        values = tuple(
            str(value or "").strip()
            for value in (
                session_id,
                tool_call_id,
                assistant_message_id,
                result_message_id,
                result_digest,
                idempotency_key,
            )
        )
        if any(not value for value in values):
            raise ValueError("tool failure job identity is required")
        expected_key = tool_failure_idempotency_key(
            session_id=session_id,
            tool_call_id=tool_call_id,
            assistant_message_id=assistant_message_id,
            result_message_id=result_message_id,
            result_digest=result_digest,
        )
        if idempotency_key != expected_key:
            raise ValueError("tool failure idempotency key does not match payload")
        timestamp = _datetime(now)
        payload = {
            "session_id": session_id,
            "tool_call_id": tool_call_id,
            "assistant_message_id": assistant_message_id,
            "result_message_id": result_message_id,
            "result_digest": result_digest,
        }
        try:
            async with AsyncSessionLocal() as db, db.begin():
                existing = await db.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    _ensure_tool_failure_identity(existing, payload)
                    return AnalysisJob(
                        job_id=existing.job_id,
                        job_type=existing.job_type,
                        payload_version=existing.payload_version,
                        payload=existing.payload,
                        status=existing.status,
                        idempotency_key=existing.idempotency_key,
                        available_at=_iso(existing.available_at),
                        created_at=_iso(existing.created_at),
                        updated_at=_iso(existing.updated_at),
                        started_at=_optional_iso(existing.started_at),
                        finished_at=_optional_iso(existing.finished_at),
                        result_id=existing.result_id,
                        error_code=existing.error_code,
                        worker_id=existing.worker_id,
                        lease_expires_at=_optional_iso(existing.lease_expires_at),
                        heartbeat_at=_optional_iso(existing.heartbeat_at),
                        lease_version=existing.lease_version,
                    )
                row = AnalysisJobRow(
                    job_id=f"job_{uuid4().hex[:32]}",
                    job_type=TOOL_FAILURE_JOB_TYPE,
                    payload_version=TOOL_FAILURE_PAYLOAD_VERSION,
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
                db.add(row)
                await db.flush()
                return AnalysisJob(
                    job_id=row.job_id,
                    job_type=row.job_type,
                    payload_version=row.payload_version,
                    payload=row.payload,
                    status=row.status,
                    idempotency_key=row.idempotency_key,
                    available_at=_iso(row.available_at),
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    started_at=_optional_iso(row.started_at),
                    finished_at=_optional_iso(row.finished_at),
                    result_id=row.result_id,
                    error_code=row.error_code,
                    worker_id=row.worker_id,
                    lease_expires_at=_optional_iso(row.lease_expires_at),
                    heartbeat_at=_optional_iso(row.heartbeat_at),
                    lease_version=row.lease_version,
                )
        except IntegrityError:
            async with AsyncSessionLocal() as db:
                existing = await db.scalar(
                    select(AnalysisJobRow).where(
                        AnalysisJobRow.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                _ensure_tool_failure_identity(existing, payload)
                return AnalysisJob(
                    job_id=existing.job_id,
                    job_type=existing.job_type,
                    payload_version=existing.payload_version,
                    payload=existing.payload,
                    status=existing.status,
                    idempotency_key=existing.idempotency_key,
                    available_at=_iso(existing.available_at),
                    created_at=_iso(existing.created_at),
                    updated_at=_iso(existing.updated_at),
                    started_at=_optional_iso(existing.started_at),
                    finished_at=_optional_iso(existing.finished_at),
                    result_id=existing.result_id,
                    error_code=existing.error_code,
                    worker_id=existing.worker_id,
                    lease_expires_at=_optional_iso(existing.lease_expires_at),
                    heartbeat_at=_optional_iso(existing.heartbeat_at),
                    lease_version=existing.lease_version,
                )

    async def claim_next_feedback_analysis_job(self, now: str) -> AnalysisJob | None:
        timestamp = _datetime(now)
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.scalar(
                select(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_type == "feedback_analysis",
                    _claimable_job_filter(timestamp),
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
            _assign_lease(row, timestamp, self.worker_id, self.lease_seconds)
            row.updated_at = timestamp
            await db.flush()
            return AnalysisJob(
                job_id=row.job_id,
                job_type=row.job_type,
                payload_version=row.payload_version,
                payload=row.payload,
                status=row.status,
                idempotency_key=row.idempotency_key,
                available_at=_iso(row.available_at),
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                result_id=row.result_id,
                error_code=row.error_code,
                worker_id=row.worker_id,
                lease_expires_at=_optional_iso(row.lease_expires_at),
                heartbeat_at=_optional_iso(row.heartbeat_at),
                lease_version=row.lease_version,
            )

    async def claim_next_correction_signal_analysis_job(
        self, now: str
    ) -> AnalysisJob | None:
        timestamp = _datetime(now)
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.scalar(
                select(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_type == CORRECTION_SIGNAL_JOB_TYPE,
                    _claimable_job_filter(timestamp),
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
            _assign_lease(row, timestamp, self.worker_id, self.lease_seconds)
            row.updated_at = timestamp
            await db.flush()
            return AnalysisJob(
                job_id=row.job_id,
                job_type=row.job_type,
                payload_version=row.payload_version,
                payload=row.payload,
                status=row.status,
                idempotency_key=row.idempotency_key,
                available_at=_iso(row.available_at),
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                result_id=row.result_id,
                error_code=row.error_code,
                worker_id=row.worker_id,
                lease_expires_at=_optional_iso(row.lease_expires_at),
                heartbeat_at=_optional_iso(row.heartbeat_at),
                lease_version=row.lease_version,
            )

    async def claim_next_tool_failure_analysis_job(
        self, now: str
    ) -> AnalysisJob | None:
        timestamp = _datetime(now)
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.scalar(
                select(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_type == TOOL_FAILURE_JOB_TYPE,
                    _claimable_job_filter(timestamp),
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
            _assign_lease(row, timestamp, self.worker_id, self.lease_seconds)
            row.updated_at = timestamp
            await db.flush()
            return AnalysisJob(
                job_id=row.job_id,
                job_type=row.job_type,
                payload_version=row.payload_version,
                payload=row.payload,
                status=row.status,
                idempotency_key=row.idempotency_key,
                available_at=_iso(row.available_at),
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                result_id=row.result_id,
                error_code=row.error_code,
                worker_id=row.worker_id,
                lease_expires_at=_optional_iso(row.lease_expires_at),
                heartbeat_at=_optional_iso(row.heartbeat_at),
                lease_version=row.lease_version,
            )

    async def claim_next_dataset_sample_build_job(self, now: str) -> AnalysisJob | None:
        """Claim exactly one sample build and mark its sample as building.

        The sample status update is in the same transaction as the job claim,
        so the UI never sees a running build whose sample still looks idle.
        """

        timestamp = _datetime(now)
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.scalar(
                select(AnalysisJobRow)
                .where(
                    AnalysisJobRow.job_type == DATASET_SAMPLE_BUILD_JOB_TYPE,
                    _claimable_job_filter(timestamp),
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
            payload = row.payload
            sample_id = str(payload.get("sample_id") or "").strip()
            generation = payload.get("generation")
            if not sample_id or not isinstance(generation, int) or generation < 1:
                row.status = "failed"
                row.finished_at = timestamp
                row.updated_at = timestamp
                row.error_code = "dataset_sample_build_payload_invalid"
                await db.flush()
                return AnalysisJob(
                    job_id=row.job_id,
                    job_type=row.job_type,
                    payload_version=row.payload_version,
                    payload=row.payload,
                    status=row.status,
                    idempotency_key=row.idempotency_key,
                    available_at=_iso(row.available_at),
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    started_at=_optional_iso(row.started_at),
                    finished_at=_optional_iso(row.finished_at),
                    result_id=row.result_id,
                    error_code=row.error_code,
                    worker_id=row.worker_id,
                    lease_expires_at=_optional_iso(row.lease_expires_at),
                    heartbeat_at=_optional_iso(row.heartbeat_at),
                    lease_version=row.lease_version,
                )
            sample = await db.scalar(
                select(FeedbackDatasetSampleRow)
                .where(FeedbackDatasetSampleRow.sample_id == sample_id)
                .with_for_update()
            )
            if (
                sample is None
                or sample.generation != generation
                or sample.active_job_id != row.job_id
                or sample.status not in {"pending", "building"}
            ):
                row.status = "cancelled"
                row.finished_at = timestamp
                row.updated_at = timestamp
                row.error_code = "sample_build_superseded"
                await db.flush()
                return AnalysisJob(
                    job_id=row.job_id,
                    job_type=row.job_type,
                    payload_version=row.payload_version,
                    payload=row.payload,
                    status=row.status,
                    idempotency_key=row.idempotency_key,
                    available_at=_iso(row.available_at),
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    started_at=_optional_iso(row.started_at),
                    finished_at=_optional_iso(row.finished_at),
                    result_id=row.result_id,
                    error_code=row.error_code,
                    worker_id=row.worker_id,
                    lease_expires_at=_optional_iso(row.lease_expires_at),
                    heartbeat_at=_optional_iso(row.heartbeat_at),
                    lease_version=row.lease_version,
                )
            row.status = "running"
            row.started_at = timestamp
            _assign_lease(row, timestamp, self.worker_id, self.lease_seconds)
            row.updated_at = timestamp
            sample.status = "building"
            sample.updated_at = timestamp
            await db.flush()
            return AnalysisJob(
                job_id=row.job_id,
                job_type=row.job_type,
                payload_version=row.payload_version,
                payload=row.payload,
                status=row.status,
                idempotency_key=row.idempotency_key,
                available_at=_iso(row.available_at),
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                result_id=row.result_id,
                error_code=row.error_code,
                worker_id=row.worker_id,
                lease_expires_at=_optional_iso(row.lease_expires_at),
                heartbeat_at=_optional_iso(row.heartbeat_at),
                lease_version=row.lease_version,
            )

    async def mark_succeeded(
        self,
        job_id: str,
        result_id: str,
        finished_at: str,
        *,
        worker_id: str | None = None,
        lease_version: int | None = None,
    ) -> AnalysisJob:
        return await self._mark_finished(
            job_id=job_id,
            status="succeeded",
            finished_at=finished_at,
            result_id=result_id,
            error_code=None,
            worker_id=worker_id,
            lease_version=lease_version,
        )

    async def mark_failed(
        self,
        job_id: str,
        error_code: str,
        finished_at: str,
        *,
        worker_id: str | None = None,
        lease_version: int | None = None,
    ) -> AnalysisJob:
        return await self._mark_finished(
            job_id=job_id,
            status="failed",
            finished_at=finished_at,
            result_id=None,
            error_code=error_code,
            worker_id=worker_id,
            lease_version=lease_version,
        )

    async def mark_cancelled(
        self,
        job_id: str,
        error_code: str,
        finished_at: str,
        *,
        worker_id: str | None = None,
        lease_version: int | None = None,
    ) -> AnalysisJob:
        return await self._mark_finished(
            job_id=job_id,
            status="cancelled",
            finished_at=finished_at,
            result_id=None,
            error_code=error_code,
            worker_id=worker_id,
            lease_version=lease_version,
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
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(AnalysisJobRow, job_id, with_for_update=True)
            if row is None:
                raise FileNotFoundError(f"analysis job not found: {job_id}")
            if row.job_type != "feedback_analysis":
                raise ValueError("only feedback analysis jobs can be requeued")
            if row.status != "failed":
                raise ValueError(f"cannot requeue analysis job in status {row.status}")
            if row.result_id is not None:
                raise ValueError("failed analysis job with a result cannot be requeued")

            requeued = AnalysisJob(
                job_id=row.job_id,
                job_type=row.job_type,
                payload_version=row.payload_version,
                payload=row.payload,
                status=row.status,
                idempotency_key=row.idempotency_key,
                available_at=_iso(row.available_at),
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                result_id=row.result_id,
                error_code=row.error_code,
                worker_id=row.worker_id,
                lease_expires_at=_optional_iso(row.lease_expires_at),
                heartbeat_at=_optional_iso(row.heartbeat_at),
                lease_version=row.lease_version,
            ).requeue_failed_feedback_analysis(available_at)
            row.status = requeued.status
            row.available_at = timestamp
            row.started_at = None
            row.finished_at = None
            row.result_id = None
            row.error_code = None
            _clear_lease(row)
            row.updated_at = timestamp
            await db.flush()
            return AnalysisJob(
                job_id=row.job_id,
                job_type=row.job_type,
                payload_version=row.payload_version,
                payload=row.payload,
                status=row.status,
                idempotency_key=row.idempotency_key,
                available_at=_iso(row.available_at),
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                result_id=row.result_id,
                error_code=row.error_code,
                worker_id=row.worker_id,
                lease_expires_at=_optional_iso(row.lease_expires_at),
                heartbeat_at=_optional_iso(row.heartbeat_at),
                lease_version=row.lease_version,
            )

    async def recover_expired_jobs(self, now: str) -> int:
        """Return jobs whose worker lease expired to the pending queue."""

        timestamp = _datetime(now)
        recovered = 0
        async with AsyncSessionLocal() as db, db.begin():
            rows = await db.scalars(
                select(AnalysisJobRow)
                .where(
                    AnalysisJobRow.status == "running",
                    AnalysisJobRow.lease_expires_at.is_not(None),
                    AnalysisJobRow.lease_expires_at <= timestamp,
                )
                .with_for_update(skip_locked=True)
            )
            for row in rows:
                row.status = "pending"
                row.available_at = timestamp
                row.started_at = None
                row.finished_at = None
                row.result_id = None
                row.error_code = "worker_lease_expired"
                _clear_lease(row)
                row.updated_at = timestamp
                if row.job_type == DATASET_SAMPLE_BUILD_JOB_TYPE:
                    sample_id = str((row.payload or {}).get("sample_id") or "").strip()
                    if sample_id:
                        sample = await db.scalar(
                            select(FeedbackDatasetSampleRow)
                            .where(
                                FeedbackDatasetSampleRow.sample_id == sample_id,
                                FeedbackDatasetSampleRow.active_job_id == row.job_id,
                                FeedbackDatasetSampleRow.status == "building",
                            )
                            .with_for_update()
                        )
                        if sample is not None:
                            sample.status = "pending"
                            sample.updated_at = timestamp
                recovered += 1
            await db.flush()
        return recovered

    async def renew_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_version: int,
        now: str,
    ) -> AnalysisJob | None:
        """Extend an unexpired lease only for its current owner/version."""
        if not job_id.strip() or not worker_id.strip() or lease_version < 1:
            raise ValueError("job lease identity is invalid")
        timestamp = _datetime(now)
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.scalar(
                select(AnalysisJobRow)
                .where(AnalysisJobRow.job_id == job_id)
                .with_for_update()
            )
            if row is None or not _completion_lease_matches(
                row,
                worker_id=worker_id,
                lease_version=lease_version,
                timestamp=timestamp,
            ):
                return None
            row.lease_expires_at = timestamp + timedelta(seconds=self.lease_seconds)
            row.heartbeat_at = timestamp
            row.updated_at = timestamp
            await db.flush()
            return AnalysisJob(
                job_id=row.job_id,
                job_type=row.job_type,
                payload_version=row.payload_version,
                payload=row.payload,
                status=row.status,
                idempotency_key=row.idempotency_key,
                available_at=_iso(row.available_at),
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                result_id=row.result_id,
                error_code=row.error_code,
                worker_id=row.worker_id,
                lease_expires_at=_optional_iso(row.lease_expires_at),
                heartbeat_at=_optional_iso(row.heartbeat_at),
                lease_version=row.lease_version,
            )

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
        async with AsyncSessionLocal() as db, db.begin():
            rows = await db.scalars(
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
            await db.flush()
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
        async with AsyncSessionLocal() as db, db.begin():
            rows = await db.scalars(
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
            await db.flush()
        return cancelled

    async def _mark_finished(
        self,
        *,
        job_id: str,
        status: str,
        finished_at: str,
        result_id: str | None,
        error_code: str | None,
        worker_id: str | None,
        lease_version: int | None,
    ) -> AnalysisJob:
        timestamp = _datetime(finished_at)
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(AnalysisJobRow, job_id, with_for_update=True)
            if row is None:
                raise FileNotFoundError(f"analysis job not found: {job_id}")
            if worker_id is not None or lease_version is not None:
                # A late worker must not finish a lease that recovery or a
                # replacement worker has already superseded.
                if not _completion_lease_matches(
                    row,
                    worker_id=worker_id,
                    lease_version=lease_version,
                    timestamp=timestamp,
                ):
                    return AnalysisJob(
                        job_id=row.job_id,
                        job_type=row.job_type,
                        payload_version=row.payload_version,
                        payload=row.payload,
                        status=row.status,
                        idempotency_key=row.idempotency_key,
                        available_at=_iso(row.available_at),
                        created_at=_iso(row.created_at),
                        updated_at=_iso(row.updated_at),
                        started_at=_optional_iso(row.started_at),
                        finished_at=_optional_iso(row.finished_at),
                        result_id=row.result_id,
                        error_code=row.error_code,
                        worker_id=row.worker_id,
                        lease_expires_at=_optional_iso(row.lease_expires_at),
                        heartbeat_at=_optional_iso(row.heartbeat_at),
                        lease_version=row.lease_version,
                    )
            if row.status in {"succeeded", "failed", "cancelled"}:
                if (
                    row.status != status
                    or row.result_id != result_id
                    or row.error_code != error_code
                ):
                    raise ValueError(
                        "analysis job is already in a different terminal state"
                    )
                return AnalysisJob(
                    job_id=row.job_id,
                    job_type=row.job_type,
                    payload_version=row.payload_version,
                    payload=row.payload,
                    status=row.status,
                    idempotency_key=row.idempotency_key,
                    available_at=_iso(row.available_at),
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    started_at=_optional_iso(row.started_at),
                    finished_at=_optional_iso(row.finished_at),
                    result_id=row.result_id,
                    error_code=row.error_code,
                    worker_id=row.worker_id,
                    lease_expires_at=_optional_iso(row.lease_expires_at),
                    heartbeat_at=_optional_iso(row.heartbeat_at),
                    lease_version=row.lease_version,
                )
            if row.status not in {"pending", "running"}:
                raise ValueError(f"analysis job cannot finish from {row.status}")
            row.status = status
            row.finished_at = timestamp
            row.updated_at = timestamp
            row.result_id = result_id
            row.error_code = error_code
            _clear_lease(row)
            await db.flush()
            return AnalysisJob(
                job_id=row.job_id,
                job_type=row.job_type,
                payload_version=row.payload_version,
                payload=row.payload,
                status=row.status,
                idempotency_key=row.idempotency_key,
                available_at=_iso(row.available_at),
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                started_at=_optional_iso(row.started_at),
                finished_at=_optional_iso(row.finished_at),
                result_id=row.result_id,
                error_code=row.error_code,
                worker_id=row.worker_id,
                lease_expires_at=_optional_iso(row.lease_expires_at),
                heartbeat_at=_optional_iso(row.heartbeat_at),
                lease_version=row.lease_version,
            )

    async def read_job(self, job_id: str) -> AnalysisJob | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(AnalysisJobRow, job_id)
            return (
                AnalysisJob(
                    job_id=row.job_id,
                    job_type=row.job_type,
                    payload_version=row.payload_version,
                    payload=row.payload,
                    status=row.status,
                    idempotency_key=row.idempotency_key,
                    available_at=_iso(row.available_at),
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    started_at=_optional_iso(row.started_at),
                    finished_at=_optional_iso(row.finished_at),
                    result_id=row.result_id,
                    error_code=row.error_code,
                    worker_id=row.worker_id,
                    lease_expires_at=_optional_iso(row.lease_expires_at),
                    heartbeat_at=_optional_iso(row.heartbeat_at),
                    lease_version=row.lease_version,
                )
                if row is not None
                else None
            )

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
        statement = (
            statement.order_by(
                AnalysisJobRow.created_at,
                AnalysisJobRow.job_id,
            )
            .offset(offset)
            .limit(limit)
        )
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(statement)
            return tuple(
                AnalysisJob(
                    job_id=row.job_id,
                    job_type=row.job_type,
                    payload_version=row.payload_version,
                    payload=row.payload,
                    status=row.status,
                    idempotency_key=row.idempotency_key,
                    available_at=_iso(row.available_at),
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    started_at=_optional_iso(row.started_at),
                    finished_at=_optional_iso(row.finished_at),
                    result_id=row.result_id,
                    error_code=row.error_code,
                    worker_id=row.worker_id,
                    lease_expires_at=_optional_iso(row.lease_expires_at),
                    heartbeat_at=_optional_iso(row.heartbeat_at),
                    lease_version=row.lease_version,
                )
                for row in rows
            )


def _ensure_feedback_identity(row: AnalysisJobRow, feedback_id: str) -> None:
    payload = row.payload or {}
    if row.job_type != "feedback_analysis" or payload.get("feedback_id") != feedback_id:
        raise ValueError("idempotency key is already bound to another analysis input")


def _claimable_job_filter(timestamp: datetime):
    return or_(
        AnalysisJobRow.status == "pending",
        and_(
            AnalysisJobRow.status == "running",
            AnalysisJobRow.lease_expires_at.is_not(None),
            AnalysisJobRow.lease_expires_at <= timestamp,
        ),
    )


def _completion_lease_matches(
    row: AnalysisJobRow,
    *,
    worker_id: str | None,
    lease_version: int | None,
    timestamp: datetime,
) -> bool:
    return (
        bool(worker_id)
        and lease_version is not None
        and (
            row.status == "running"
            and row.worker_id == worker_id
            and row.lease_version == lease_version
            and row.lease_expires_at is not None
            and row.lease_expires_at > timestamp
        )
    )


def _assign_lease(
    row: AnalysisJobRow,
    timestamp: datetime,
    worker_id: str,
    lease_seconds: int,
) -> None:
    row.worker_id = worker_id
    row.lease_expires_at = timestamp + timedelta(seconds=lease_seconds)
    row.heartbeat_at = timestamp
    row.lease_version = int(row.lease_version or 0) + 1
    row.error_code = None


def _clear_lease(row: AnalysisJobRow) -> None:
    row.worker_id = None
    row.lease_expires_at = None
    row.heartbeat_at = None


def _ensure_correction_identity(row: AnalysisJobRow, payload: dict[str, str]) -> None:
    if row.job_type != CORRECTION_SIGNAL_JOB_TYPE or row.payload != payload:
        raise ValueError("idempotency key is already bound to another analysis input")


def _ensure_tool_failure_identity(row: AnalysisJobRow, payload: dict[str, str]) -> None:
    if row.job_type != TOOL_FAILURE_JOB_TYPE or row.payload != payload:
        raise ValueError("idempotency key is already bound to another analysis input")


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


__all__ = ["AnalysisJob", "AnalysisJobStatus", "AnalysisJobRepository"]
