from __future__ import annotations

from dataclasses import replace

import pytest

from application.feedback.dataset_service import (
    FeedbackDatasetConflict,
    FeedbackDatasetService,
)
from application.repositories.feedback_dataset_sample_repository import (
    source_digest_for_case,
)
from domain.feedback import (
    Dataset,
    DatasetSample,
    FeedbackCase,
    SampleRevision,
    SftRevisionContent,
    content_digest_for,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Collections:
    async def get_collection_for_user(self, collection_id: str, user_id: str):
        if (collection_id, user_id) != ("collection-1", "user-1"):
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id}


class _Datasets:
    async def read(self, dataset_id: str):
        return _dataset() if dataset_id == "fdset-1" else None


class _Cases:
    def __init__(self) -> None:
        self.case = _case()

    async def read_case(self, case_id: str):
        return self.case if case_id == "case-1" else None


class _Samples:
    def __init__(self) -> None:
        self.sample = _sample()
        self.revisions = {"revision-1": _revision("revision-1", "worker")}
        self.appended = None
        self.confirmed = None

    async def list_samples(self, **kwargs):
        return (self.sample,)

    async def count_samples(self, **kwargs):
        return 1

    async def read_sample(self, **kwargs):
        return self.sample

    async def read_revision(self, revision_id: str):
        return self.revisions.get(revision_id)

    async def append_human_revision(self, **kwargs):
        if kwargs["expected_revision_id"] != self.sample.current_revision_id:
            raise FeedbackDatasetConflict("sample_revision_stale")
        revision = kwargs["revision"]
        self.revisions[revision.revision_id] = revision
        self.sample = replace(
            self.sample,
            status="needs_confirmation",
            current_revision_id=revision.revision_id,
            confirmed_revision_id=None,
            confirmed_by=None,
            confirmed_at=None,
        )
        self.appended = revision
        return self.sample

    async def confirm_revision(self, **kwargs):
        if kwargs["expected_revision_id"] != self.sample.current_revision_id:
            raise FeedbackDatasetConflict("sample_revision_stale")
        self.sample = replace(
            self.sample,
            status="confirmed",
            confirmed_revision_id=kwargs["expected_revision_id"],
            confirmed_by=kwargs["confirmed_by"],
            confirmed_at="2026-09-29T01:00:00+00:00",
        )
        self.confirmed = kwargs
        return self.sample


def _dataset() -> Dataset:
    return Dataset("fdset-1", "collection-1", "SFT", "sft", {}, 1, "user-1")


def _sample() -> DatasetSample:
    return DatasetSample(
        sample_id="sample-1",
        dataset_id="fdset-1",
        source_case_id="case-1",
        status="needs_confirmation",
        current_revision_id="revision-1",
        confirmed_revision_id=None,
        generation=1,
        source_digest=source_digest_for_case(_case().to_record()),
        active_job_id=None,
        missing_reasons=(),
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


def _revision(revision_id: str, author_kind: str) -> SampleRevision:
    # Use the mapping form so the test mirrors the HTTP payload shape.
    content = SftRevisionContent.from_mapping(
        {
            "schema_version": "literature-sft.v1",
            "messages": [{"role": "user", "content": "比较 A、B。"}],
            "context": [{"document_title": "文献 A", "text": "原文"}],
            "target": "候选回答",
            "evidence": [{"document_title": "文献 A", "text": "原文"}],
        }
    )
    return SampleRevision(
        revision_id=revision_id,
        sample_id="sample-1",
        revision_no=1,
        author_kind=author_kind,  # type: ignore[arg-type]
        content=content,
        content_digest=content_digest_for(content),
        input_digest="a" * 64,
        construction_spec_version=1,
        provenance={"source_case_id": "case-1"},
        created_at="2026-09-29T00:00:00+00:00",
        created_by="user-1" if author_kind == "human" else None,
        job_id="job-1" if author_kind == "worker" else None,
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
            "inspected_sources": [{"document_title": "文献 A", "quote": "原文"}],
        },
        status="needs_annotation",
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


def _service(samples: _Samples, cases: _Cases | None = None) -> FeedbackDatasetService:
    return FeedbackDatasetService(
        repository=_Datasets(),
        collection_service=_Collections(),
        sample_repository=samples,
        case_repository=cases or _Cases(),
    )


@pytest.mark.anyio
async def test_human_edit_appends_revision_and_clears_confirmation() -> None:
    samples = _Samples()
    service = _service(samples)

    result = await service.update_sample(
        user_id="user-1",
        dataset_id="fdset-1",
        sample_id="sample-1",
        expected_revision_id="revision-1",
        content={
            "schema_version": "literature-sft.v1",
            "messages": [{"role": "user", "content": "比较 A、B。"}],
            "context": [{"document_title": "文献 A", "text": "原文"}],
            "target": "人工修订回答",
            "evidence": [{"document_title": "文献 A", "text": "原文"}],
        },
    )

    assert result.status == "needs_confirmation"
    assert result.confirmed_revision_id is None
    assert samples.appended is not None
    assert samples.appended.author_kind == "human"
    assert samples.appended.content.target == "人工修订回答"


@pytest.mark.anyio
async def test_confirmation_binds_current_revision_and_stale_edit_is_rejected() -> None:
    samples = _Samples()
    service = _service(samples)

    confirmed = await service.confirm_sample(
        user_id="user-1",
        dataset_id="fdset-1",
        sample_id="sample-1",
        expected_revision_id="revision-1",
    )
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_revision_id == "revision-1"
    assert confirmed.confirmed_by == "user-1"
    assert confirmed.confirmed_at is not None

    with pytest.raises(FeedbackDatasetConflict, match="sample_revision_stale"):
        await service.update_sample(
            user_id="user-1",
            dataset_id="fdset-1",
            sample_id="sample-1",
            expected_revision_id="old-revision",
            content={
                "schema_version": "literature-sft.v1",
                "messages": [{"role": "user", "content": "比较 A、B。"}],
                "context": [{"document_title": "文献 A", "text": "原文"}],
                "target": "晚到修改",
                "evidence": [{"document_title": "文献 A", "text": "原文"}],
            },
        )


@pytest.mark.anyio
async def test_edit_rejects_sample_when_source_case_digest_changed() -> None:
    samples = _Samples()
    cases = _Cases()
    service = _service(samples, cases)
    cases.case = replace(
        cases.case,
        context_snapshot={**cases.case.context_snapshot, "answer": "更新后的回答"},
    )

    with pytest.raises(FeedbackDatasetConflict, match="sample_source_stale"):
        await service.update_sample(
            user_id="user-1",
            dataset_id="fdset-1",
            sample_id="sample-1",
            expected_revision_id="revision-1",
            content={
                "schema_version": "literature-sft.v1",
                "messages": [{"role": "user", "content": "比较 A、B。"}],
                "context": [{"document_title": "文献 A", "text": "原文"}],
                "target": "新的人工回答",
                "evidence": [{"document_title": "文献 A", "text": "原文"}],
            },
        )


@pytest.mark.anyio
async def test_confirmation_rejects_sample_when_source_case_digest_changed() -> None:
    samples = _Samples()
    cases = _Cases()
    service = _service(samples, cases)
    cases.case = replace(
        cases.case,
        context_snapshot={**cases.case.context_snapshot, "answer": "更新后的回答"},
    )

    with pytest.raises(FeedbackDatasetConflict, match="sample_source_stale"):
        await service.confirm_sample(
            user_id="user-1",
            dataset_id="fdset-1",
            sample_id="sample-1",
            expected_revision_id="revision-1",
        )
