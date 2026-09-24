"""Versioned work envelope used by feedback analysis workers."""

from __future__ import annotations

from dataclasses import dataclass, field
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
