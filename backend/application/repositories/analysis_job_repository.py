"""Application contract for versioned feedback-analysis jobs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, Literal, Protocol

from domain.feedback.tool_failure import _text as _tool_failure_text

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

    values = tuple(
        _tool_failure_text(value, name)
        for name, value in (
            ("session_id", session_id),
            ("tool_call_id", tool_call_id),
            ("assistant_message_id", assistant_message_id),
            ("result_message_id", result_message_id),
            ("result_digest", result_digest),
        )
    )
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
        object.__setattr__(self, "payload", dict(self.payload))
        if (
            self.status in {"succeeded", "failed", "cancelled"}
            and self.finished_at is None
        ):
            raise ValueError("terminal analysis jobs require finished_at")

    @property
    def feedback_id(self) -> str | None:
        value = self.payload.get("feedback_id")
        return str(value) if value else None

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


class AnalysisJobRepository(Protocol):
    """Persistence operations used by analysis producers and workers."""

    async def enqueue_feedback_analysis(
        self,
        feedback_id: str,
        idempotency_key: str,
        now: str,
    ) -> AnalysisJob: ...

    async def enqueue_correction_signal_analysis(
        self,
        *,
        session_id: str,
        anchor_message_id: str,
        trigger_message_id: str,
        trigger_digest: str,
        idempotency_key: str,
        now: str,
    ) -> AnalysisJob: ...

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
    ) -> AnalysisJob: ...

    async def claim_next_feedback_analysis_job(self, now: str) -> AnalysisJob | None: ...

    async def claim_next_correction_signal_analysis_job(
        self, now: str
    ) -> AnalysisJob | None: ...

    async def claim_next_tool_failure_analysis_job(self, now: str) -> AnalysisJob | None: ...

    async def claim_next_dataset_sample_build_job(self, now: str) -> AnalysisJob | None: ...

    async def cancel_feedback_analysis_jobs(
        self, feedback_id: str, finished_at: str
    ) -> int: ...

    async def cancel_correction_signal_analysis_jobs(
        self, *, trigger_message_id: str, finished_at: str
    ) -> int: ...

    async def mark_succeeded(
        self,
        job_id: str,
        result_id: str,
        finished_at: str,
        *,
        worker_id: str | None = None,
        lease_version: int | None = None,
    ) -> AnalysisJob: ...

    async def mark_failed(
        self,
        job_id: str,
        error_code: str,
        finished_at: str,
        *,
        worker_id: str | None = None,
        lease_version: int | None = None,
    ) -> AnalysisJob: ...

    async def mark_cancelled(
        self,
        job_id: str,
        error_code: str,
        finished_at: str,
        *,
        worker_id: str | None = None,
        lease_version: int | None = None,
    ) -> AnalysisJob: ...

    async def requeue_failed_feedback_analysis_job(
        self,
        job_id: str,
        now: str,
    ) -> AnalysisJob: ...

    async def read_job(self, job_id: str) -> AnalysisJob | None: ...

    async def list_jobs(
        self,
        *,
        job_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[AnalysisJob, ...]: ...

    async def recover_expired_jobs(self, now: str) -> int: ...


__all__ = ["AnalysisJob", "AnalysisJobStatus", "AnalysisJobRepository"]
