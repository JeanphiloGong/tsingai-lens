"""Worker for evidence-backed task dataset sample build jobs."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from application.feedback.evaluation_sample_builder import EvaluationBuildNeedsInput, EvaluationSampleBuilder
from application.feedback.preference_sample_builder import PreferenceBuildNeedsInput, PreferenceSampleBuilder
from application.feedback.sft_sample_builder import (
    SftBuildNeedsInput,
    SftSampleBuilderProtocol,
)
from application.feedback.worker_lease import LeaseLostError, run_with_lease_heartbeat
from domain.feedback import SampleRevision
from domain.feedback.sample_revision import content_digest_for
from repositories.analysis_job_repository import (
    AnalysisJobRepo,
    DATASET_SAMPLE_BUILD_JOB_TYPE,
    DATASET_SAMPLE_BUILD_PAYLOAD_VERSION,
)
from repositories.feedback_case_repository import FeedbackCaseRepo
from repositories.feedback_dataset_repository import (
    FeedbackDatasetRepo,
)
from repositories.feedback_dataset_sample_repository import (
    FeedbackDatasetSampleRepo,
    source_digest_for_case,
)

logger = logging.getLogger(__name__)


class DatasetSampleBuildWorker:
    def __init__(
        self,
        *,
        builder: SftSampleBuilderProtocol | None = None,
        builders: Mapping[str, Any] | None = None,
        build_timeout_seconds: float = 600,
    ) -> None:
        if not math.isfinite(build_timeout_seconds) or build_timeout_seconds <= 0:
            raise ValueError("sample build timeout must be finite and positive")
        self.build_timeout_seconds = build_timeout_seconds
        self.builders = dict(builders or {})
        if builder is not None:
            # Runtime overrides can continue to provide a custom SFT builder.
            self.builders.setdefault("sft", builder)
        self.builders.setdefault("preference", PreferenceSampleBuilder())
        self.builders.setdefault("evaluation", EvaluationSampleBuilder())

    async def run_once(self) -> Any | None:
        now = datetime.now(timezone.utc).isoformat()
        await AnalysisJobRepo.recover_expired_jobs(now=now)
        job = await AnalysisJobRepo.claim_next_dataset_sample_build_job(now=now)
        if job is None:
            return None
        if job.status != "running":
            return job
        timeout = min(self.build_timeout_seconds, 600)
        if job.lease_expires_at:
            remaining = (datetime.fromisoformat(job.lease_expires_at) - datetime.now(timezone.utc)).total_seconds()
            timeout = min(timeout, remaining - 5)
        if timeout <= 0:
            return await self._read_finished(job)
        try:
            async with asyncio.timeout(timeout):
                return await run_with_lease_heartbeat(
                    job,
                    lambda: self._build(job),
                )
        except LeaseLostError:
            return await self._read_finished(job)
        except TimeoutError:
            payload = job.payload
            await FeedbackDatasetSampleRepo.complete_build(
                job=job, sample_id=payload["sample_id"],
                generation=payload["generation"], revision=None,
                outcome="failed", error_code="dataset_sample_build_timeout",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            return await self._read_finished(job)

    async def _build(self, job: Any) -> Any:
        payload = job.payload
        try:
            dataset_id = _required_payload(payload, "dataset_id")
            sample_id = _required_payload(payload, "sample_id")
            generation = _positive_int(payload.get("generation"), "generation")
            spec_version = _positive_int(payload.get("spec_version"), "spec_version")
            source_digest = _required_payload(payload, "source_digest")
            if job.payload_version != DATASET_SAMPLE_BUILD_PAYLOAD_VERSION:
                raise ValueError("unsupported_dataset_sample_build_payload")
            if job.job_type != DATASET_SAMPLE_BUILD_JOB_TYPE:
                raise ValueError("unsupported_dataset_sample_build_job")
            dataset = await FeedbackDatasetRepo.read(dataset_id)
            sample = await FeedbackDatasetSampleRepo.read_sample(
                dataset_id=dataset_id,
                sample_id=sample_id,
            )
            if dataset is None or sample is None:
                raise ValueError("dataset_sample_build_source_missing")
            if (
                sample.generation != generation
                or sample.active_job_id != job.job_id
                or sample.source_digest != source_digest
                or dataset.spec_version != spec_version
            ):
                return await self._complete_stale(job, sample_id, generation)
            case = await FeedbackCaseRepo.read_case(sample.source_case_id)
            if case is None or case.collection_id != dataset.collection_id:
                raise ValueError("dataset_sample_build_case_missing")
            if case.status == "withdrawn" or source_digest_for_case(case) != source_digest:
                await FeedbackDatasetSampleRepo.complete_build(
                    job=job,
                    sample_id=sample_id,
                    generation=generation,
                    revision=None,
                    outcome="needs_input",
                    missing_reasons=("source_changed_since_collection",),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                return await self._read_finished(job)
            annotation = await FeedbackCaseRepo.read_annotation(case.case_id)
            task_builder = self.builders.get(dataset.task_type)
            if task_builder is None:
                raise ValueError("unsupported_dataset_task_type")
            previous = (
                await FeedbackDatasetSampleRepo.read_revision(sample.current_revision_id)
                if sample.current_revision_id else None
            )
            built = await task_builder.build(
                dataset=dataset,
                sample=sample,
                case=case,
                annotation=annotation,
                review_note=payload.get("review_note"),
                **({"previous_revision": previous} if dataset.task_type == "preference" else {}),
            )
            if isinstance(built, (SftBuildNeedsInput, PreferenceBuildNeedsInput, EvaluationBuildNeedsInput)):
                await FeedbackDatasetSampleRepo.complete_build(
                    job=job,
                    sample_id=sample_id,
                    generation=generation,
                    revision=None,
                    outcome="needs_input",
                    missing_reasons=built.missing_reasons,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                return await self._read_finished(job)

            content = built.content
            provenance = built.provenance
            expected_schema = {
                "sft": "literature-sft.v1",
                "preference": "literature-preference.v1",
                "evaluation": "literature-evaluation.v1",
            }.get(dataset.task_type)
            if content.schema_version != expected_schema:
                raise ValueError("dataset_sample_build_content_task_mismatch")

            if (
                payload.get("review_note")
                and previous is not None
                and previous.content_digest == content_digest_for(content)
            ):
                await FeedbackDatasetSampleRepo.complete_build(
                    job=job,
                    sample_id=sample_id,
                    generation=generation,
                    revision=None,
                    outcome="needs_input",
                    missing_reasons=("candidate_unchanged_after_rebuild",),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                return await self._read_finished(job)

            revision_no = 1
            if previous is not None:
                revision_no = previous.revision_no + 1
            revision = SampleRevision.build_worker(
                revision_id=f"revision_{uuid4().hex[:32]}",
                sample_id=sample_id,
                revision_no=revision_no,
                content=content,
                input_digest=sample.source_digest,
                construction_spec_version=dataset.spec_version,
                provenance={
                    **provenance,
                    **({"review_note": payload["review_note"]} if payload.get("review_note") else {}),
                },
                created_at=datetime.now(timezone.utc).isoformat(),
                job_id=job.job_id,
            )
            await FeedbackDatasetSampleRepo.complete_build(
                job=job,
                sample_id=sample_id,
                generation=generation,
                revision=revision,
                outcome="candidate",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            return await self._read_finished(job)
        except Exception as exc:  # noqa: BLE001
            logger.exception("dataset sample build failed job_id=%s", job.job_id)
            try:
                await FeedbackDatasetSampleRepo.complete_build(
                    job=job,
                    sample_id=payload.get("sample_id"),
                    generation=payload.get("generation"),
                    revision=None,
                    outcome="failed",
                    error_code=_error_code(exc),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
            except Exception:  # noqa: BLE001
                logger.exception("dataset sample build failure persistence failed job_id=%s", job.job_id)
            return await self._read_finished(job)

    async def _complete_stale(self, job: Any, sample_id: str, generation: int) -> Any:
        await FeedbackDatasetSampleRepo.complete_build(
            job=job,
            sample_id=sample_id,
            generation=generation,
            revision=None,
            outcome="failed",
            error_code="sample_build_superseded",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return await self._read_finished(job)

    async def _read_finished(self, job: Any) -> Any:
        finished = await AnalysisJobRepo.read_job(job.job_id)
        if finished is None:
            raise RuntimeError(f"sample build job disappeared: {job.job_id}")
        return finished


def _required_payload(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"dataset_sample_build_{name}_missing")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"dataset_sample_build_{name}_invalid")
    return value


def _error_code(exc: Exception) -> str:
    value = str(exc).strip()
    if value.startswith("dataset_sample_build_") and value.replace("_", "").isalnum():
        return value[:128]
    return "dataset_sample_build_failed"


__all__ = ["DatasetSampleBuildWorker"]
