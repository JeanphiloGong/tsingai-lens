"""Worker for evidence-backed task dataset sample build jobs."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import logging
from uuid import uuid4
from typing import Any, Mapping

from application.feedback.sft_sample_builder import (
    SftSampleBuilderProtocol,
)
from application.feedback.preference_sample_builder import PreferenceSampleBuilder
from application.feedback.evaluation_sample_builder import EvaluationSampleBuilder
from application.repositories.feedback_case_repository import FeedbackCaseRepository
from application.repositories.feedback_dataset_repository import FeedbackDatasetRepository
from application.repositories.feedback_dataset_sample_repository import (
    FeedbackDatasetSampleRepository,
)
from domain.feedback import (
    DATASET_SAMPLE_BUILD_JOB_TYPE,
    DATASET_SAMPLE_BUILD_PAYLOAD_VERSION,
    SampleRevision,
)
from domain.feedback.dataset_sample import source_digest_for_case
from domain.feedback.sample_revision import content_digest_for


logger = logging.getLogger(__name__)


class DatasetSampleBuildWorker:
    def __init__(
        self,
        *,
        job_repository: Any,
        dataset_repository: FeedbackDatasetRepository,
        sample_repository: FeedbackDatasetSampleRepository,
        case_repository: FeedbackCaseRepository,
        builder: SftSampleBuilderProtocol | None = None,
        builders: Mapping[str, Any] | None = None,
    ) -> None:
        self.job_repository = job_repository
        self.dataset_repository = dataset_repository
        self.sample_repository = sample_repository
        self.case_repository = case_repository
        self.builders = dict(builders or {})
        if builder is not None:
            # Runtime overrides can continue to provide a custom SFT builder.
            self.builders.setdefault("sft", builder)
        self.builders.setdefault("preference", PreferenceSampleBuilder())
        self.builders.setdefault("evaluation", EvaluationSampleBuilder())

    async def run_once(self) -> Any | None:
        now = datetime.now(timezone.utc).isoformat()
        job = await self.job_repository.claim_next_dataset_sample_build_job(now=now)
        if job is None:
            return None
        if job.status != "running":
            return job
        payload = dict(job.payload or {})
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
            dataset = await self.dataset_repository.read(dataset_id)
            sample = await self.sample_repository.read_sample(
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
            case = await self.case_repository.read_case(sample.source_case_id)
            if case is None or case.collection_id != dataset.collection_id:
                raise ValueError("dataset_sample_build_case_missing")
            if source_digest_for_case(case.to_record()) != source_digest:
                await self.sample_repository.complete_build(
                    job=job,
                    sample_id=sample_id,
                    generation=generation,
                    revision=None,
                    outcome="needs_input",
                    missing_reasons=("source_changed_since_collection",),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                return await self._read_finished(job, status="succeeded", result_id=sample_id)
            annotation = await self.case_repository.read_annotation(case.case_id)
            task_builder = self.builders.get(dataset.task_type)
            if task_builder is None:
                raise ValueError("unsupported_dataset_task_type")
            built = await task_builder.build(
                dataset=dataset,
                sample=sample,
                case=case,
                annotation=annotation,
            )
            missing_reasons = getattr(built, "missing_reasons", None)
            if missing_reasons is not None and not hasattr(built, "content"):
                await self.sample_repository.complete_build(
                    job=job,
                    sample_id=sample_id,
                    generation=generation,
                    revision=None,
                    outcome="needs_input",
                    missing_reasons=tuple(missing_reasons),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                return await self._read_finished(job, status="succeeded", result_id=sample_id)

            content = getattr(built, "content", None)
            provenance = getattr(built, "provenance", None)
            expected_schema = {
                "sft": "literature-sft.v1",
                "preference": "literature-preference.v1",
                "evaluation": "literature-evaluation.v1",
            }.get(dataset.task_type)
            if content is None or not isinstance(provenance, dict) or content.schema_version != expected_schema:
                raise ValueError("dataset_sample_build_content_task_mismatch")

            previous = (
                await self.sample_repository.read_revision(sample.current_revision_id)
                if sample.current_revision_id else None
            )
            if (
                payload.get("review_note")
                and previous is not None
                and previous.content_digest == content_digest_for(content)
            ):
                await self.sample_repository.complete_build(
                    job=job,
                    sample_id=sample_id,
                    generation=generation,
                    revision=None,
                    outcome="needs_input",
                    missing_reasons=("candidate_unchanged_after_rebuild",),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                return await self._read_finished(job, status="succeeded", result_id=sample_id)

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
            await self.sample_repository.complete_build(
                job=job,
                sample_id=sample_id,
                generation=generation,
                revision=revision,
                outcome="candidate",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            return await self._read_finished(job, status="succeeded", result_id=revision.revision_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("dataset sample build failed job_id=%s", job.job_id)
            try:
                await self.sample_repository.complete_build(
                    job=job,
                    sample_id=str(payload.get("sample_id") or ""),
                    generation=int(payload.get("generation") or 0),
                    revision=None,
                    outcome="failed",
                    error_code=_error_code(exc),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
            except Exception:  # noqa: BLE001
                logger.exception("dataset sample build failure persistence failed job_id=%s", job.job_id)
            return await self._read_finished(
                job,
                status="failed",
                error_code=_error_code(exc),
            )

    async def _complete_stale(self, job: Any, sample_id: str, generation: int) -> Any:
        await self.sample_repository.complete_build(
            job=job,
            sample_id=sample_id,
            generation=generation,
            revision=None,
            outcome="failed",
            error_code="sample_build_superseded",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return await self._read_finished(job, status="cancelled", error_code="sample_build_superseded")

    async def _read_finished(
        self,
        job: Any,
        *,
        status: str,
        result_id: str | None = None,
        error_code: str | None = None,
    ) -> Any:
        reader = getattr(self.job_repository, "read_job", None)
        if callable(reader):
            finished = await reader(job.job_id)
            if finished is not None and finished.status not in {"pending", "running"}:
                return finished
        return replace(
            job,
            status=status,
            result_id=result_id,
            error_code=error_code,
            finished_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )


def _required_payload(payload: dict[str, Any], name: str) -> str:
    value = str(payload.get(name) or "").strip()
    if not value:
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
