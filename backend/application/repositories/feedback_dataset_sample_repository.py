"""Application persistence contract for task dataset samples and revisions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal, Protocol

from application.repositories.analysis_job_repository import AnalysisJob
from domain.feedback.dataset_sample import DatasetSample, SampleAction, _is_sha256
from domain.feedback.sample_revision import SampleRevision

DATASET_SAMPLE_BUILD_JOB_TYPE = "dataset_sample_build"
DATASET_SAMPLE_BUILD_PAYLOAD_VERSION = 1


def sample_action_digest(
    *, action: SampleAction, expected_revision_id: str | None, reason: str | None
) -> str:
    payload = {
        "action": action,
        "expected_revision_id": expected_revision_id,
        "reason": (reason or "").strip(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def source_digest_for_case(case_record: dict[str, Any]) -> str:
    encoded = json.dumps(
        case_record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def sample_build_idempotency_key(
    *,
    sample_id: str,
    generation: int,
    spec_version: int,
    source_digest: str,
) -> str:
    if generation < 1 or spec_version < 1 or not _is_sha256(source_digest):
        raise ValueError("invalid sample build identity")
    return ":".join(
        (
            DATASET_SAMPLE_BUILD_JOB_TYPE,
            sample_id,
            str(generation),
            str(spec_version),
            source_digest,
        )
    )


def build_job_payload(
    *,
    dataset_id: str,
    sample_id: str,
    generation: int,
    spec_version: int,
    source_digest: str,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "sample_id": sample_id,
        "generation": generation,
        "spec_version": spec_version,
        "source_digest": source_digest,
    }


@dataclass(frozen=True)
class CollectedDatasetSample:
    sample: DatasetSample
    job: AnalysisJob | None


@dataclass(frozen=True)
class ConfirmedDatasetMember:
    sample: DatasetSample
    revision: SampleRevision


class DatasetSampleRevisionConflict(ValueError):
    """The sample changed after the caller read its current revision."""


class DatasetSampleActionConflict(ValueError):
    """An action key or the sample generation changed."""


BuildCompletionKind = Literal["candidate", "needs_input", "failed"]


class FeedbackDatasetSampleRepository(Protocol):
    async def collect(
        self,
        *,
        samples: tuple[DatasetSample, ...],
        jobs: tuple[AnalysisJob, ...],
    ) -> tuple[CollectedDatasetSample, ...]: ...

    async def read_sample(
        self, *, dataset_id: str, sample_id: str
    ) -> DatasetSample | None: ...

    async def list_samples(
        self,
        *,
        dataset_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[DatasetSample, ...]: ...

    async def read_revision(self, revision_id: str) -> SampleRevision | None: ...

    async def count_samples(self, *, dataset_id: str, status: str | None = None) -> int: ...

    async def read_confirmed_members(
        self, *, dataset_id: str
    ) -> tuple[ConfirmedDatasetMember, ...]: ...

    async def append_human_revision(
        self,
        *,
        sample_id: str,
        expected_revision_id: str | None,
        expected_generation: int | None = None,
        revision: SampleRevision,
        updated_at: str,
    ) -> DatasetSample: ...

    async def confirm_revision(
        self,
        *,
        sample_id: str,
        expected_revision_id: str,
        confirmed_by: str,
        confirmed_at: str,
    ) -> DatasetSample: ...

    async def apply_action(
        self,
        *,
        dataset_id: str,
        sample_id: str,
        expected_revision_id: str | None,
        expected_generation: int,
        action: SampleAction,
        reason: str | None,
        actor_id: str,
        idempotency_key: str,
        request_digest: str,
        source_digest: str | None,
        job: AnalysisJob | None,
        now: str,
    ) -> DatasetSample: ...

    async def complete_build(
        self,
        *,
        job: AnalysisJob,
        sample_id: str,
        generation: int,
        revision: SampleRevision | None,
        outcome: BuildCompletionKind,
        missing_reasons: tuple[str, ...] = (),
        error_code: str | None = None,
        finished_at: str,
    ) -> DatasetSample | None: ...


__all__ = [
    "BuildCompletionKind",
    "CollectedDatasetSample",
    "ConfirmedDatasetMember",
    "DatasetSampleRevisionConflict",
    "DatasetSampleActionConflict",
    "FeedbackDatasetSampleRepository",
]
