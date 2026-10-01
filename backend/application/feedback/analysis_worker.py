"""Explicit one-shot worker for feedback analysis jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from application.feedback.analysis_handler import AnalysisInputError, FeedbackAnalysisHandler


logger = logging.getLogger(__name__)


class FeedbackAnalysisWorker:
    def __init__(
        self,
        *,
        job_repository: Any,
        case_repository: Any,
        handler: FeedbackAnalysisHandler,
    ) -> None:
        self.job_repository = job_repository
        self.case_repository = case_repository
        self.handler = handler

    async def run_once(self) -> Any | None:
        now = datetime.now(timezone.utc).isoformat()
        recover = getattr(self.job_repository, "recover_expired_jobs", None)
        if callable(recover):
            await recover(now=now)
        job = await self.job_repository.claim_next_feedback_analysis_job(now=now)
        if job is None:
            return None
        try:
            result, context_snapshot, source_signal_ids = await self.handler.handle(job)
        except AnalysisInputError as exc:
            if str(exc) in {"feedback_withdrawn", "feedback_version_superseded"}:
                return await self.job_repository.mark_cancelled(
                    job_id=job.job_id,
                    error_code=str(exc),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    worker_id=job.worker_id,
                    lease_version=job.lease_version,
                )
            logger.warning("feedback analysis input rejected job_id=%s code=%s", job.job_id, exc)
            return await self.job_repository.mark_failed(
                job_id=job.job_id,
                error_code=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat(),
                worker_id=job.worker_id,
                lease_version=job.lease_version,
            )
        except Exception:  # noqa: BLE001
            logger.exception("feedback analysis worker failed job_id=%s", job.job_id)
            return await self.job_repository.mark_failed(
                job_id=job.job_id,
                error_code="feedback_analysis_failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                worker_id=job.worker_id,
                lease_version=job.lease_version,
            )

        try:
            # The repository commits the result, case, and three sample queues together.
            await self.case_repository.upsert_case_from_analysis(
                result,
                context_snapshot=context_snapshot,
                source_signal_ids=source_signal_ids,
                now=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:  # noqa: BLE001
            logger.exception("feedback analysis persistence failed job_id=%s", job.job_id)
            return await self.job_repository.mark_failed(
                job_id=job.job_id,
                error_code="feedback_analysis_persistence_failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                worker_id=job.worker_id,
                lease_version=job.lease_version,
            )
        return await self.job_repository.mark_succeeded(
            job_id=job.job_id,
            result_id=result.result_id,
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id=job.worker_id,
            lease_version=job.lease_version,
        )


__all__ = ["FeedbackAnalysisWorker"]
