"""One-shot worker for message-derived correction signal jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import AsyncExitStack
import logging
import httpx
from openai import AsyncOpenAI

from exceptions import ServiceUnavailableException
from infra.llm.model_credentials import provider_options
from repositories.model_connection_repository import ModelConnectionRepo
from repositories.analysis_job_repository import AnalysisJob, AnalysisJobRepo, LeaseLostError
from repositories.feedback_case_repository import FeedbackCaseRepo, FeedbackCaseWriteConflict

from application.feedback.errors import AnalysisInputError
from application.feedback.correction_scope_analysis import OpenAICorrectionSignalAnalysisEngine
from application.feedback.correction_signal_handler import CorrectionSignalAnalysisEngine, analyze_correction_signal_job


logger = logging.getLogger(__name__)


async def execute_correction_signal_analysis_job(
    job: AnalysisJob, *, engine: CorrectionSignalAnalysisEngine | None = None,
    model_name: str | None = None,
) -> AnalysisJob:
    try:
        async with AsyncExitStack() as resources:
            if engine is None:
                connection = await ModelConnectionRepo.read_assigned_connection("feedback")
                client = await resources.enter_async_context(AsyncOpenAI(
                    **provider_options(connection), http_client=httpx.AsyncClient(follow_redirects=False)
                ))
                engine = OpenAICorrectionSignalAnalysisEngine(client=client, model=connection.model)
                model_name = connection.model
            result, context_snapshot, source_signal_ids = await analyze_correction_signal_job(
                job, engine=engine, model_name=model_name,
            )
    except ServiceUnavailableException as exc:
        return await AnalysisJobRepo.mark_failed(
            job_id=job.job_id,
            error_code=exc.data["code"],
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id=job.worker_id,
            lease_version=job.lease_version,
        )
    except AnalysisInputError as exc:
        code = str(exc)
        if code in {
            "correction_signal_withdrawn",
            "correction_signal_superseded",
            "correction_signal_not_candidate",
        }:
            return await AnalysisJobRepo.mark_cancelled(
                job_id=job.job_id,
                error_code=code,
                finished_at=datetime.now(timezone.utc).isoformat(),
                worker_id=job.worker_id,
                lease_version=job.lease_version,
            )
        logger.warning(
            "correction signal input rejected job_id=%s code=%s",
            job.job_id,
            code,
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
        logger.exception("correction signal worker failed job_id=%s", job.job_id)
        return await AnalysisJobRepo.mark_failed(
            job_id=job.job_id,
            error_code="correction_signal_analysis_failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id=job.worker_id,
            lease_version=job.lease_version,
        )

    try:
        await FeedbackCaseRepo.upsert_case_from_correction_signal(
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
        logger.exception("correction signal persistence failed job_id=%s", job.job_id)
        return await AnalysisJobRepo.mark_failed(
            job_id=job.job_id,
            error_code="correction_signal_persistence_failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id=job.worker_id,
            lease_version=job.lease_version,
        )
    return await AnalysisJobRepo.read_job(job.job_id)


__all__ = ["execute_correction_signal_analysis_job"]
