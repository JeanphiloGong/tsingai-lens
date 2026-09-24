"""Application contract for versioned feedback-analysis jobs."""

from __future__ import annotations

from typing import Protocol

from domain.feedback.analysis_job import AnalysisJob


class AnalysisJobRepository(Protocol):
    """Persistence operations used by analysis producers and workers."""

    async def enqueue_feedback_analysis(
        self,
        feedback_id: str,
        idempotency_key: str,
        now: str,
    ) -> AnalysisJob: ...

    async def claim_next_feedback_analysis_job(self, now: str) -> AnalysisJob | None: ...

    async def cancel_feedback_analysis_jobs(
        self, feedback_id: str, finished_at: str
    ) -> int: ...

    async def mark_succeeded(
        self,
        job_id: str,
        result_id: str,
        finished_at: str,
    ) -> AnalysisJob: ...

    async def mark_failed(
        self,
        job_id: str,
        error_code: str,
        finished_at: str,
    ) -> AnalysisJob: ...

    async def mark_cancelled(
        self,
        job_id: str,
        error_code: str,
        finished_at: str,
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


__all__ = ["AnalysisJobRepository"]
