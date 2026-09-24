"""Versioned work envelope used by feedback analysis workers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal


AnalysisJobStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True)
class AnalysisJob:
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

    def __post_init__(self) -> None:
        if not self.job_id or not self.job_type:
            raise ValueError("analysis job identity is required")
        if self.payload_version < 1:
            raise ValueError("analysis job payload version must be positive")
        if not self.idempotency_key:
            raise ValueError("analysis job idempotency key is required")
        object.__setattr__(self, "payload", dict(self.payload))
        if self.status in {"succeeded", "failed", "cancelled"} and self.finished_at is None:
            raise ValueError("terminal analysis jobs require finished_at")

    @property
    def feedback_id(self) -> str | None:
        value = self.payload.get("feedback_id")
        return str(value) if value else None

    def requeue_failed_feedback_analysis(self, available_at: str) -> "AnalysisJob":
        """Return a failed feedback-analysis job to the pending queue.

        Requeueing is an explicit operator action.  A job that already has a
        result cannot be reused because that would make one job identity point
        at two analysis attempts.  The failed run's error and timestamps are
        cleared; its immutable identity, payload, and idempotency key remain.
        """
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
