from __future__ import annotations

from dataclasses import replace

import pytest

from application.feedback.sample_build_worker import DatasetSampleBuildWorker
from application.feedback.sft_sample_builder import SftSampleBuilder
from domain.feedback import (
    AnalysisJob,
    Dataset,
    DatasetSample,
    FeedbackCase,
    SftRevisionContent,
    build_job_payload,
    sample_build_idempotency_key,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Jobs:
    def __init__(self, job: AnalysisJob) -> None:
        self.job = job

    async def claim_next_dataset_sample_build_job(self, *, now: str):
        if self.job.status != "pending":
            return None
        self.job = replace(self.job, status="running", started_at=now, updated_at=now)
        return self.job

    async def read_job(self, job_id: str):
        return self.job


class _Datasets:
    async def read(self, dataset_id: str):
        return _dataset() if dataset_id == "fdset-1" else None


class _Cases:
    async def read_case(self, case_id: str):
        return _case() if case_id == "case-1" else None

    async def read_annotation(self, case_id: str):
        return None


class _Samples:
    def __init__(self, sample: DatasetSample):
        self.sample = sample
        self.revision = None
        self.completed = None

    async def read_sample(self, *, dataset_id: str, sample_id: str):
        return self.sample

    async def read_revision(self, revision_id: str):
        return self.revision

    async def complete_build(self, **kwargs):
        self.completed = kwargs
        revision = kwargs.get("revision")
        if revision is not None:
            self.revision = revision
            self.sample = replace(
                self.sample,
                status="needs_confirmation",
                current_revision_id=revision.revision_id,
                active_job_id=None,
            )
        else:
            self.sample = replace(
                self.sample,
                status="needs_input" if kwargs["outcome"] == "needs_input" else "build_failed",
                active_job_id=None,
            )
        return self.sample


def _dataset() -> Dataset:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return Dataset("fdset-1", "collection-1", "SFT", "sft", {}, 1, "user-1", now, now)


def _sample() -> DatasetSample:
    return DatasetSample.pending(
        sample_id="sample-1",
        dataset_id="fdset-1",
        source_case_id="case-1",
        source_digest="a" * 64,
        active_job_id="job-1",
        now="2026-09-29T00:00:00+00:00",
    )


def _case() -> FeedbackCase:
    return FeedbackCase(
        case_id="case-1",
        collection_id="collection-1",
        session_id="session-1",
        anchor_message_id="answer-1",
        source_signal_ids=(),
        analysis_result_ids=(),
        context_snapshot={
            "question": "比较 A、B。",
            "answer": "原回答",
            "candidate_target": "基于证据的回答",
            "inspected_sources": [
                {"document_title": "文献 B", "source_ref": "blk-1", "quote": "证据原文"}
            ],
        },
        status="needs_annotation",
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


def _job() -> AnalysisJob:
    payload = build_job_payload(
        dataset_id="fdset-1",
        sample_id="sample-1",
        generation=1,
        spec_version=1,
        source_digest="a" * 64,
    )
    return AnalysisJob(
        job_id="job-1",
        job_type="dataset_sample_build",
        payload_version=1,
        payload=payload,
        status="pending",
        idempotency_key=sample_build_idempotency_key(
            sample_id="sample-1",
            generation=1,
            spec_version=1,
            source_digest="a" * 64,
        ),
        available_at="2026-09-29T00:00:00+00:00",
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


async def test_worker_publishes_candidate_as_needs_confirmation() -> None:
    samples = _Samples(_sample())
    jobs = _Jobs(_job())
    result = await DatasetSampleBuildWorker(
        job_repository=jobs,
        dataset_repository=_Datasets(),
        sample_repository=samples,
        case_repository=_Cases(),
        builder=SftSampleBuilder(),
    ).run_once()

    assert result.status == "succeeded"
    assert samples.completed["outcome"] == "candidate"
    assert samples.sample.status == "needs_confirmation"
    assert samples.sample.confirmed_revision_id is None
    assert samples.revision is not None


async def test_worker_leaves_missing_material_as_needs_input() -> None:
    samples = _Samples(replace(_sample(), source_digest="b" * 64))
    job = replace(_job(), payload={**_job().payload, "source_digest": "b" * 64})
    jobs = _Jobs(job)
    cases = _Cases()
    cases.read_case = lambda case_id: _missing_case(case_id)
    result = await DatasetSampleBuildWorker(
        job_repository=jobs,
        dataset_repository=_Datasets(),
        sample_repository=samples,
        case_repository=cases,
        builder=SftSampleBuilder(),
    ).run_once()

    assert result.status == "succeeded"
    assert samples.completed["outcome"] == "needs_input"
    assert samples.sample.status == "needs_input"


async def _missing_case(case_id: str):
    return replace(
        _case(),
        context_snapshot={"question": "缺少证据", "answer": "原回答", "inspected_sources": []},
    )
