"""One-shot worker for message-derived correction signal jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from application.feedback.analysis_handler import AnalysisInputError
from application.feedback.correction_signal_handler import CorrectionSignalAnalysisHandler


logger = logging.getLogger(__name__)


class CorrectionSignalAnalysisWorker:
    """Process only ``correction_signal_analysis`` jobs.

    Keeping this worker separate from the frozen P1 feedback worker makes the
    new source identity and cancellation semantics explicit at the runtime
    boundary.
    """

    def __init__(
        self,
        *,
        job_repository: Any,
        case_repository: Any,
        handler: CorrectionSignalAnalysisHandler,
        dataset_service: Any | None = None,
    ) -> None:
        self.job_repository = job_repository
        self.case_repository = case_repository
        self.handler = handler
        self.dataset_service = dataset_service

    async def run_once(self) -> Any | None:
        now = datetime.now(timezone.utc).isoformat()
        recover = getattr(self.job_repository, "recover_expired_jobs", None)
        if callable(recover):
            await recover(now=now)
        job = await self.job_repository.claim_next_correction_signal_analysis_job(now=now)
        if job is None:
            return None
        try:
            result, context_snapshot, source_signal_ids = await self.handler.handle(job)
        except AnalysisInputError as exc:
            code = str(exc)
            if code in {
                "correction_signal_withdrawn",
                "correction_signal_superseded",
                "correction_signal_not_candidate",
            }:
                return await self.job_repository.mark_cancelled(
                    job_id=job.job_id,
                    error_code=code,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
            logger.warning(
                "correction signal input rejected job_id=%s code=%s",
                job.job_id,
                code,
            )
            return await self.job_repository.mark_failed(
                job_id=job.job_id,
                error_code=code,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "correction signal worker failed job_id=%s", job.job_id
            )
            return await self.job_repository.mark_failed(
                job_id=job.job_id,
                error_code="correction_signal_analysis_failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )

        try:
            case = await self.case_repository.upsert_case_from_correction_signal(
                result,
                context_snapshot=context_snapshot,
                source_signal_ids=source_signal_ids,
                now=datetime.now(timezone.utc).isoformat(),
            )
            if self.dataset_service is not None and case is not None:
                await self.dataset_service.enqueue_case_samples(
                    collection_id=case.collection_id,
                    case_id=case.case_id,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "correction signal persistence failed job_id=%s", job.job_id
            )
            return await self.job_repository.mark_failed(
                job_id=job.job_id,
                error_code="correction_signal_persistence_failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        return await self.job_repository.mark_succeeded(
            job_id=job.job_id,
            result_id=result.result_id,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )


__all__ = ["CorrectionSignalAnalysisWorker"]
