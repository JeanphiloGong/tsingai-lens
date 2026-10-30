from __future__ import annotations

from application.feedback import sample_build_worker, worker_lease

from application.feedback.sample_builder_support import EvaluationSampleModelOutput, PreferenceSampleModelOutput, SftSampleModelOutput

from domain.feedback.sample_revision import PreferenceRevisionContent


import asyncio
from dataclasses import replace

import pytest

from application.feedback.preference_sample_builder import PreferenceSampleBuilder
from application.feedback.sample_build_worker import DatasetSampleBuildWorker
from application.feedback.sft_sample_builder import SftSampleBuilder
from domain.feedback import (
    Dataset,
    DatasetSample,
    FeedbackCase,
    SampleRevision,
)
from repositories.analysis_job_repository import AnalysisJob
from repositories.feedback_dataset_sample_repository import (
    sample_build_idempotency_key,
    source_digest_for_case,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Jobs:
    def __init__(self, job: AnalysisJob) -> None:
        self.job = job

    async def recover_expired_jobs(self, *, now):
        return 0

    async def read_job(self, job_id):
        return self.job if self.job.job_id == job_id else None

    async def renew_lease(self, **kwargs):
        assert kwargs["worker_id"] == self.job.worker_id
        assert kwargs["lease_version"] == self.job.lease_version
        return self.job

    async def claim_next_dataset_sample_build_job(self, *, now: str):
        if self.job.status != "pending":
            return None
        self.job = replace(self.job, status="running", started_at=now, updated_at=now, worker_id="worker-1", lease_version=1)
        return self.job

class _Datasets:
    def __init__(self, dataset=None) -> None:
        self.dataset = dataset or _dataset()

    async def read(self, dataset_id: str):
        return self.dataset if dataset_id == "fdset-1" else None


class _Cases:
    async def read_case(self, case_id: str):
        return _case() if case_id == "case-1" else None

    async def read_annotation(self, case_id: str):
        return None


class _Samples:
    def __init__(self, sample: DatasetSample, jobs: _Jobs):
        self.jobs = jobs
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
        self.jobs.job = replace(
            self.jobs.job,
            status="failed" if kwargs["outcome"] == "failed" else "succeeded",
            result_id=(revision.revision_id if revision else self.sample.sample_id)
                if kwargs["outcome"] != "failed" else None,
            error_code=kwargs.get("error_code"),
            finished_at=kwargs["finished_at"], updated_at=kwargs["finished_at"],
        )
        return self.sample


def _dataset() -> Dataset:
    return Dataset("fdset-1", "collection-1", "SFT", "sft", {}, 1, "user-1")


def _sample() -> DatasetSample:
    return DatasetSample.pending(
        sample_id="sample-1",
        dataset_id="fdset-1",
        source_case_id="case-1",
        source_digest=source_digest_for_case(_case()),
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
            "messages": [{"role": "user", "content": "比较 A、B。"}], "question": "比较 A、B。",
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
    source_digest = source_digest_for_case(_case())
    payload = {
        "dataset_id": "fdset-1",
        "sample_id": "sample-1",
        "generation": 1,
        "spec_version": 1,
        "source_digest": source_digest,
    }
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
            source_digest=source_digest,
        ),
        available_at="2026-09-29T00:00:00+00:00",
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


async def test_worker_publishes_candidate_as_needs_confirmation() -> None:
    jobs = _Jobs(_job())
    samples = _Samples(_sample(), jobs)
    sample_build_worker.AnalysisJobRepo = jobs
    worker_lease.AnalysisJobRepo = sample_build_worker.AnalysisJobRepo
    sample_build_worker.FeedbackDatasetRepo = _Datasets()
    sample_build_worker.FeedbackDatasetSampleRepo = samples
    sample_build_worker.FeedbackCaseRepo = _Cases()
    result = await DatasetSampleBuildWorker(builder=SftSampleBuilder()).run_once()

    assert result.status == "succeeded"
    assert samples.completed["outcome"] == "candidate"
    assert samples.sample.status == "needs_confirmation"
    assert samples.sample.confirmed_revision_id is None
    assert samples.revision is not None


@pytest.mark.parametrize("task_type", ["sft", "preference", "evaluation"])
async def test_generated_content_is_saved_as_an_unconfirmed_worker_revision(task_type: str) -> None:
    from application.feedback.evaluation_sample_builder import EvaluationSampleBuilder

    case = replace(_case(), context_snapshot={
        key: value for key, value in _case().context_snapshot.items() if key != "candidate_target"
    })
    sample = replace(_sample(), source_digest=source_digest_for_case(case))
    jobs = _Jobs(_job_for_case(case))
    samples = _Samples(sample, jobs)
    if task_type == "preference":
        previous = SampleRevision.build_worker(
            revision_id="previous-revision",
            sample_id=sample.sample_id,
            revision_no=1,
            content=PreferenceRevisionContent(
                schema_version="literature-preference.v1",
                messages=({"role": "user", "content": "比较 A、B。"},),
                context=({"document_title": "文献 B", "text": "证据原文"},),
                evidence=({"document_title": "文献 B", "text": "证据原文"},),
                response_a="当前回答 A",
                response_b="当前回答 B",
                rationale="旧理由",
                suggested_preference=None,
            ),
            input_digest=sample.source_digest,
            construction_spec_version=1,
            provenance={"evidence_records": [{"source_ref": "blk-1"}]},
            created_at="2026-09-29T00:00:00+00:00",
            job_id="previous-job",
        )
        samples.revision = previous
        samples.sample = replace(sample, current_revision_id=previous.revision_id)

    class Cases(_Cases):
        async def read_case(self, case_id: str):
            return case

    class Generator:
        model_name = "test-model"

        async def generate(self, **kwargs):
            assert kwargs["task_type"] == task_type
            assert kwargs["context"][0]["text"] == "证据原文"
            assert kwargs["review_note"] == "核对比较条件"
            if task_type == "sft":
                return SftSampleModelOutput.model_validate({"target": "基于原文生成的回答", "missing_reasons": []})
            if task_type == "preference":
                assert kwargs["snapshot"]["response_a"] == "当前回答 A"
                assert kwargs["snapshot"]["response_b"] == "当前回答 B"
                return PreferenceSampleModelOutput.model_validate({"response_a": "当前回答 A", "response_b": "修正后的回答 B",
                    "suggested_preference": "b", "rationale": "按意见核对了条件。", "missing_reasons": []})
            return EvaluationSampleModelOutput.model_validate({"reference": "基于原文生成的回答", "criteria": ["必须说明比较条件"], "missing_reasons": []})

    job = _job_for_case(case)
    job = replace(job, payload={**job.payload, "review_note": "核对比较条件"})
    jobs.job = job
    generator = Generator()
    builder = {"sft": SftSampleBuilder, "preference": PreferenceSampleBuilder,
        "evaluation": EvaluationSampleBuilder}[task_type](generator=generator)
    sample_build_worker.AnalysisJobRepo = jobs
    worker_lease.AnalysisJobRepo = sample_build_worker.AnalysisJobRepo
    sample_build_worker.FeedbackDatasetRepo = _Datasets(replace(_dataset(), task_type=task_type))
    sample_build_worker.FeedbackDatasetSampleRepo = samples
    sample_build_worker.FeedbackCaseRepo = Cases()
    result = await DatasetSampleBuildWorker(builders={task_type: builder}).run_once()

    assert result.status == "succeeded"
    assert samples.sample.status == "needs_confirmation"
    assert samples.sample.confirmed_revision_id is None
    assert samples.revision.author_kind == "worker"
    assert samples.revision.provenance["builder"] == "test-model"
    assert samples.revision.provenance["review_note"] == "核对比较条件"
    if task_type == "preference":
        assert samples.revision.revision_no == 2
        assert samples.revision.provenance["reviewed_revision_id"] == "previous-revision"
        assert samples.revision.content.human_preference is None


async def test_worker_leaves_missing_material_as_needs_input() -> None:
    job = replace(_job(), payload={**_job().payload, "source_digest": "b" * 64})
    jobs = _Jobs(job)
    samples = _Samples(replace(_sample(), source_digest="b" * 64), jobs)
    cases = _Cases()
    cases.read_case = lambda case_id: _missing_case(case_id)
    sample_build_worker.AnalysisJobRepo = jobs
    worker_lease.AnalysisJobRepo = sample_build_worker.AnalysisJobRepo
    sample_build_worker.FeedbackDatasetRepo = _Datasets()
    sample_build_worker.FeedbackDatasetSampleRepo = samples
    sample_build_worker.FeedbackCaseRepo = cases
    result = await DatasetSampleBuildWorker(builder=SftSampleBuilder()).run_once()

    assert result.status == "succeeded"
    assert samples.completed["outcome"] == "needs_input"
    assert samples.sample.status == "needs_input"


async def test_worker_rejects_source_changed_after_collect() -> None:
    jobs = _Jobs(_job())
    samples = _Samples(_sample(), jobs)
    cases = _Cases()
    cases.read_case = lambda case_id: _missing_case(case_id)

    sample_build_worker.AnalysisJobRepo = jobs
    worker_lease.AnalysisJobRepo = sample_build_worker.AnalysisJobRepo
    sample_build_worker.FeedbackDatasetRepo = _Datasets()
    sample_build_worker.FeedbackDatasetSampleRepo = samples
    sample_build_worker.FeedbackCaseRepo = cases
    result = await DatasetSampleBuildWorker(builder=SftSampleBuilder()).run_once()

    assert result.status == "succeeded"
    assert samples.completed["outcome"] == "needs_input"
    assert samples.completed["missing_reasons"] == ("source_changed_since_collection",)
    assert samples.revision is None


async def test_worker_dispatches_preference_builder_by_dataset_task_type() -> None:
    from dataclasses import replace

    dataset = replace(_dataset(), task_type="preference")
    case = replace(
        _case(),
        context_snapshot={
            "messages": [{"role": "user", "content": "比较 A、B。"}], "question": "比较 A、B。",
            "answer": "回答 A",
            "candidate_target": "回答 B",
            "inspected_sources": [{"document_title": "文献 B", "quote": "图注原文"}],
        },
    )
    sample = DatasetSample.pending(
        sample_id="sample-1",
        dataset_id="fdset-1",
        source_case_id="case-1",
        source_digest=source_digest_for_case(case),
        active_job_id="job-1",
        now="2026-09-29T00:00:00+00:00",
    )
    jobs = _Jobs(_job_for_case(case))
    samples = _Samples(sample, jobs)

    class Cases(_Cases):
        async def read_case(self, case_id: str):
            return case

    class Generator:
        model_name = "preference-judge"

        async def generate(self, **inputs):
            assert inputs["review_note"] is None
            return PreferenceSampleModelOutput.model_validate({"suggested_preference": "b", "rationale": "回答 B 保留图注的条件。"})

    sample_build_worker.AnalysisJobRepo = jobs
    worker_lease.AnalysisJobRepo = sample_build_worker.AnalysisJobRepo
    sample_build_worker.FeedbackDatasetRepo = _Datasets(dataset)
    sample_build_worker.FeedbackDatasetSampleRepo = samples
    sample_build_worker.FeedbackCaseRepo = Cases()
    worker = DatasetSampleBuildWorker(builders={"preference": PreferenceSampleBuilder(generator=Generator())})
    result = await worker.run_once()

    assert result.status == "succeeded"
    assert samples.revision is not None
    assert samples.revision.content.schema_version == "literature-preference.v1"
    assert samples.revision.content.suggested_preference == "b"
    assert samples.revision.content.rationale == "回答 B 保留图注的条件。"
    assert samples.revision.content.human_preference is None
    assert samples.sample.status == "needs_confirmation"


def _job_for_case(case: FeedbackCase) -> AnalysisJob:
    source_digest = source_digest_for_case(case)
    payload = {
        "dataset_id": "fdset-1",
        "sample_id": "sample-1",
        "generation": 1,
        "spec_version": 1,
        "source_digest": source_digest,
    }
    return AnalysisJob(
        job_id="job-1",
        job_type="dataset_sample_build",
        payload_version=1,
        payload=payload,
        status="pending",
        idempotency_key=sample_build_idempotency_key(
            sample_id="sample-1", generation=1, spec_version=1, source_digest=source_digest
        ),
        available_at="2026-09-29T00:00:00+00:00",
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


async def _missing_case(case_id: str):
    return replace(
        _case(),
        context_snapshot={"messages": [{"role": "user", "content": "缺少证据"}], "question": "缺少证据", "answer": "原回答", "inspected_sources": []},
    )


async def test_worker_reports_persisted_state_when_completion_loses_its_lease():
    replacement = replace(_job(), status="running", worker_id="new-worker", lease_version=2)

    class ReclaimedJobs(_Jobs):
        async def read_job(self, job_id: str):
            return replacement

    class LostLeaseSamples(_Samples):
        async def complete_build(self, **inputs):
            assert inputs["outcome"] == "candidate"
            return None

    jobs = ReclaimedJobs(_job())
    samples = LostLeaseSamples(replace(_sample(), status="building"), jobs)
    sample_build_worker.AnalysisJobRepo = jobs
    worker_lease.AnalysisJobRepo = sample_build_worker.AnalysisJobRepo
    sample_build_worker.FeedbackDatasetRepo = _Datasets()
    sample_build_worker.FeedbackDatasetSampleRepo = samples
    sample_build_worker.FeedbackCaseRepo = _Cases()
    result = await DatasetSampleBuildWorker(builder=SftSampleBuilder()).run_once()
    assert result == replacement
    assert samples.sample.status == "building"
    assert samples.sample.current_revision_id is None


async def test_worker_times_out_a_build_before_its_lease_expires():
    class HangingBuilder:
        async def build(self, **kwargs):
            await asyncio.Event().wait()

    jobs = _Jobs(_job())
    samples = _Samples(_sample(), jobs)
    sample_build_worker.AnalysisJobRepo = jobs
    worker_lease.AnalysisJobRepo = sample_build_worker.AnalysisJobRepo
    sample_build_worker.FeedbackDatasetRepo = _Datasets()
    sample_build_worker.FeedbackDatasetSampleRepo = samples
    sample_build_worker.FeedbackCaseRepo = _Cases()
    worker = DatasetSampleBuildWorker(builders={"sft": HangingBuilder()}, build_timeout_seconds=0.01)
    result = await worker.run_once()
    assert result.status == "failed"
    assert samples.sample.status == "build_failed"
    assert samples.completed["error_code"] == "dataset_sample_build_timeout"


async def test_withdrawn_case_never_invokes_a_builder():
    class UnusedBuilder:
        async def build(self, **kwargs):
            raise AssertionError("withdrawn cases must not consume model calls")

    class WithdrawnCases(_Cases):
        async def read_case(self, case_id):
            return replace(_case(), status="withdrawn")

    jobs = _Jobs(_job())
    samples = _Samples(_sample(), jobs)
    sample_build_worker.AnalysisJobRepo = jobs
    worker_lease.AnalysisJobRepo = sample_build_worker.AnalysisJobRepo
    sample_build_worker.FeedbackDatasetRepo = _Datasets()
    sample_build_worker.FeedbackDatasetSampleRepo = samples
    sample_build_worker.FeedbackCaseRepo = WithdrawnCases()
    result = await DatasetSampleBuildWorker(builders={"sft": UnusedBuilder()}).run_once()
    assert result.status == "succeeded"
    assert samples.sample.status == "needs_input"


async def test_disappeared_job_cannot_be_reported_as_success():
    class MissingJobs(_Jobs):
        async def read_job(self, job_id):
            return None

    class DeletedJobSamples(_Samples):
        async def complete_build(self, **kwargs):
            # The transaction found no matching persisted job, so nothing was published.
            return None

    jobs = MissingJobs(_job())
    samples = DeletedJobSamples(_sample(), jobs)
    sample_build_worker.AnalysisJobRepo = jobs
    worker_lease.AnalysisJobRepo = sample_build_worker.AnalysisJobRepo
    sample_build_worker.FeedbackDatasetRepo = _Datasets()
    sample_build_worker.FeedbackDatasetSampleRepo = samples
    sample_build_worker.FeedbackCaseRepo = _Cases()
    worker = DatasetSampleBuildWorker(builder=SftSampleBuilder())
    with pytest.raises(RuntimeError, match="sample build job disappeared: job-1"):
        await worker.run_once()
    assert samples.revision is None
    assert samples.sample.current_revision_id is None
