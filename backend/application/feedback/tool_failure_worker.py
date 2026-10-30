"""One-shot worker for failed Chat tool analysis jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from repositories.analysis_job_repository import AnalysisJobRepo
from repositories.feedback_case_repository import FeedbackCaseRepo

from application.feedback.analysis_handler import AnalysisInputError
from application.feedback.tool_failure_handler import ToolFailureAnalysisHandler
from application.feedback.worker_lease import LeaseLostError, run_with_lease_heartbeat


logger = logging.getLogger(__name__)


class ToolFailureAnalysisWorker:
    """Process only ``tool_failure_analysis`` jobs."""

    def __init__(
        self,
        *,
        handler: ToolFailureAnalysisHandler,
    ) -> None:
        self.handler = handler

    async def run_once(self) -> Any | None:
        now = datetime.now(timezone.utc).isoformat()
        await AnalysisJobRepo.recover_expired_jobs(now=now)
        job = await AnalysisJobRepo.claim_next_tool_failure_analysis_job(now=now)
        if job is None:
            return None
        try:
            result, context_snapshot, source_signal_ids = await run_with_lease_heartbeat(
                job,
                lambda: self.handler.handle(job),
            )
        except LeaseLostError:
            return await AnalysisJobRepo.read_job(job.job_id)
        except AnalysisInputError as exc:
            code = str(exc)
            if code in {
                "tool_failure_withdrawn",
                "tool_failure_superseded",
                "tool_failure_not_candidate",
            }:
                return await AnalysisJobRepo.mark_cancelled(
                    job_id=job.job_id,
                    error_code=code,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    worker_id=job.worker_id,
                    lease_version=job.lease_version,
                )
            logger.warning(
                "tool failure input rejected job_id=%s code=%s", job.job_id, code
            )
            return await AnalysisJobRepo.mark_failed(
                job_id=job.job_id,
                error_code=code,
                finished_at=datetime.now(timezone.utc).isoformat(),
                worker_id=job.worker_id,
                lease_version=job.lease_version,
            )
        except Exception:  # noqa: BLE001
            logger.exception("tool failure worker failed job_id=%s", job.job_id)
            return await AnalysisJobRepo.mark_failed(
                job_id=job.job_id,
                error_code="tool_failure_analysis_failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                worker_id=job.worker_id,
                lease_version=job.lease_version,
            )

        try:
            await FeedbackCaseRepo.upsert_case_from_tool_failure(
                result,
                context_snapshot=context_snapshot,
                source_signal_ids=source_signal_ids,
                now=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "tool failure persistence failed job_id=%s", job.job_id
            )
            return await AnalysisJobRepo.mark_failed(
                job_id=job.job_id,
                error_code="tool_failure_persistence_failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                worker_id=job.worker_id,
                lease_version=job.lease_version,
            )
        return await AnalysisJobRepo.mark_succeeded(
            job_id=job.job_id,
            result_id=result.result_id,
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id=job.worker_id,
            lease_version=job.lease_version,
        )


__all__ = ["ToolFailureAnalysisWorker"]
