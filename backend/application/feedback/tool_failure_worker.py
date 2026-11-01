"""One-shot worker for failed Chat tool analysis jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from repositories.analysis_job_repository import AnalysisJob, AnalysisJobRepo, LeaseLostError
from repositories.feedback_case_repository import FeedbackCaseRepo, FeedbackCaseWriteConflict

from application.feedback.errors import AnalysisInputError
from application.feedback.tool_failure_handler import ToolFailureAnalysisEngine, analyze_tool_failure_job


logger = logging.getLogger(__name__)


async def execute_tool_failure_analysis_job(
    job: AnalysisJob, *, engine: ToolFailureAnalysisEngine, model_name: str
) -> AnalysisJob:
    try:
        result, context_snapshot, source_signal_ids = await analyze_tool_failure_job(
            job,
            engine=engine,
            model_name=model_name,
        )
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
    except LeaseLostError:
        raise
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
        logger.exception("tool failure persistence failed job_id=%s", job.job_id)
        return await AnalysisJobRepo.mark_failed(
            job_id=job.job_id,
            error_code="tool_failure_persistence_failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id=job.worker_id,
            lease_version=job.lease_version,
        )
    return await AnalysisJobRepo.read_job(job.job_id)


__all__ = ["execute_tool_failure_analysis_job"]
