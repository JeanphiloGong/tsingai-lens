"""Explicit one-shot worker for feedback analysis jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from repositories.analysis_job_repository import AnalysisJob, AnalysisJobRepo, LeaseLostError
from repositories.feedback_case_repository import FeedbackCaseRepo, FeedbackCaseWriteConflict

from application.feedback.analysis_handler import AnalysisInputError, FeedbackAnalysisEngine, analyze_feedback_job


logger = logging.getLogger(__name__)


async def execute_feedback_analysis_job(
    job: AnalysisJob, *, engine: FeedbackAnalysisEngine, model_name: str
) -> AnalysisJob:
    try:
        result, context_snapshot, source_signal_ids = await analyze_feedback_job(
            job,
            engine=engine,
            model_name=model_name,
        )
    except AnalysisInputError as exc:
        if str(exc) in {"feedback_withdrawn", "feedback_version_superseded"}:
            return await AnalysisJobRepo.mark_cancelled(
                job_id=job.job_id,
                error_code=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat(),
                worker_id=job.worker_id,
                lease_version=job.lease_version,
            )
        logger.warning(
            "feedback analysis input rejected job_id=%s code=%s", job.job_id, exc
        )
        return await AnalysisJobRepo.mark_failed(
            job_id=job.job_id,
            error_code=str(exc),
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id=job.worker_id,
            lease_version=job.lease_version,
        )
    except LeaseLostError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("feedback analysis worker failed job_id=%s", job.job_id)
        return await AnalysisJobRepo.mark_failed(
            job_id=job.job_id,
            error_code="feedback_analysis_failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id=job.worker_id,
            lease_version=job.lease_version,
        )

    try:
        # The repository commits the result, case, and three sample queues together.
        await FeedbackCaseRepo.upsert_case_from_analysis(
            result,
            job=job,
            context_snapshot=context_snapshot,
            source_signal_ids=source_signal_ids,
            now=datetime.now(timezone.utc).isoformat(),
        )
    except FeedbackCaseWriteConflict as exc:
        return await AnalysisJobRepo.mark_cancelled(
            job_id=job.job_id,
            error_code=exc.reason,
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id=job.worker_id,
            lease_version=job.lease_version,
        )
    except LeaseLostError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("feedback analysis persistence failed job_id=%s", job.job_id)
        return await AnalysisJobRepo.mark_failed(
            job_id=job.job_id,
            error_code="feedback_analysis_persistence_failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id=job.worker_id,
            lease_version=job.lease_version,
        )
    return await AnalysisJobRepo.read_job(job.job_id)


__all__ = ["execute_feedback_analysis_job"]
