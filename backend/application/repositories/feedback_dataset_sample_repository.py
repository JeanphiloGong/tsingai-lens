"""Application persistence contract for task dataset samples and revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from domain.feedback.analysis_job import AnalysisJob
from domain.feedback.dataset_sample import DatasetSample, SampleAction
from domain.feedback.sample_revision import SampleRevision


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
