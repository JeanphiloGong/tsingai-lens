"""Application persistence contract for task dataset samples and revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from domain.feedback.analysis_job import AnalysisJob
from domain.feedback.dataset_sample import DatasetSample
from domain.feedback.sample_revision import SampleRevision


@dataclass(frozen=True)
class CollectedDatasetSample:
    sample: DatasetSample
    job: AnalysisJob | None


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
    "FeedbackDatasetSampleRepository",
]
