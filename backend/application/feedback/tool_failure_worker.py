"""One-shot worker for failed Chat tool analysis jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from application.feedback.analysis_handler import AnalysisInputError
from application.feedback.tool_failure_handler import ToolFailureAnalysisHandler


logger = logging.getLogger(__name__)


class ToolFailureAnalysisWorker:
    """Process only ``tool_failure_analysis`` jobs."""

    def __init__(
        self,
        *,
        job_repository: Any,
        case_repository: Any,
        handler: ToolFailureAnalysisHandler,
    ) -> None:
        self.job_repository = job_repository
        self.case_repository = case_repository
        self.handler = handler

    async def run_once(self) -> Any | None:
        now = datetime.now(timezone.utc).isoformat()
        recover = getattr(self.job_repository, "recover_expired_jobs", None)
        if callable(recover):
            await recover(now=now)
        job = await self.job_repository.claim_next_tool_failure_analysis_job(now=now)
        if job is None:
            return None
        try:
            result, context_snapshot, source_signal_ids = await self.handler.handle(job)
        except AnalysisInputError as exc:
            code = str(exc)
            if code in {
                "tool_failure_withdrawn",
                "tool_failure_superseded",
                "tool_failure_not_candidate",
            }:
                return await self.job_repository.mark_cancelled(
                    job_id=job.job_id,
                    error_code=code,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
            logger.warning(
                "tool failure input rejected job_id=%s code=%s", job.job_id, code
            )
            return await self.job_repository.mark_failed(
                job_id=job.job_id,
                error_code=code,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:  # noqa: BLE001
            logger.exception("tool failure worker failed job_id=%s", job.job_id)
            return await self.job_repository.mark_failed(
                job_id=job.job_id,
                error_code="tool_failure_analysis_failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )

        try:
            await self.case_repository.upsert_case_from_tool_failure(
                result,
                context_snapshot=context_snapshot,
                source_signal_ids=source_signal_ids,
                now=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "tool failure persistence failed job_id=%s", job.job_id
            )
            return await self.job_repository.mark_failed(
                job_id=job.job_id,
                error_code="tool_failure_persistence_failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        return await self.job_repository.mark_succeeded(
            job_id=job.job_id,
            result_id=result.result_id,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )


__all__ = ["ToolFailureAnalysisWorker"]
