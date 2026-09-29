from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from application.feedback.dataset_service import (
    FeedbackDatasetConflict,
    FeedbackDatasetService,
)
from application.repositories.feedback_dataset_sample_repository import DatasetSampleActionConflict
from domain.feedback import Dataset, DatasetSample, FeedbackCase
from domain.feedback.dataset_sample import ensure_action_allowed, sample_action_digest


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
        now = datetime.now(timezone.utc)
        return Dataset(dataset_id, "collection-1", "SFT", "sft", {}, 1, "user-1", now, now)


class _Cases:
    async def read_case(self, case_id: str):
        return FeedbackCase(
            case_id=case_id,
            collection_id="collection-1",
            session_id="session-1",
            anchor_message_id="answer-1",
            source_signal_ids=(),
            analysis_result_ids=(),
            context_snapshot={"question": "核对图注", "answer": "旧回答"},
            status="needs_annotation",
            created_at="2026-09-29T00:00:00+00:00",
            updated_at="2026-09-29T00:00:00+00:00",
        )


class _Samples:
    def __init__(self, sample: DatasetSample):
        self.sample = sample
        self.calls: list[dict] = []

    async def read_sample(self, **kwargs):
        return self.sample

    async def apply_action(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["expected_generation"] != self.sample.generation:
            raise DatasetSampleActionConflict("sample_revision_stale")
        action = kwargs["action"]
        self.sample = replace(
            self.sample,
            status="pending" if action in {"rebuild", "retry"} else "discarded" if action == "discard" else "needs_input",
            generation=self.sample.generation + 1,
            active_job_id=kwargs["job"].job_id if kwargs["job"] else None,
            confirmed_revision_id=None,
            confirmed_by=None,
            confirmed_at=None,
        )
        return self.sample


def _sample(status: str = "needs_confirmation") -> DatasetSample:
    return DatasetSample(
        sample_id="sample-1",
        dataset_id="fdset-1",
        source_case_id="case-1",
        status=status,  # type: ignore[arg-type]
        current_revision_id="revision-1",
        confirmed_revision_id=None,
        generation=1,
        source_digest="a" * 64,
        active_job_id="job-1" if status in {"pending", "building"} else None,
        missing_reasons=(),
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


def _service(samples: _Samples) -> FeedbackDatasetService:
    return FeedbackDatasetService(
        repository=_Datasets(),
        collection_service=_Collections(),
        sample_repository=samples,
        case_repository=_Cases(),
    )


async def test_rebuild_creates_new_generation_and_review_note() -> None:
    samples = _Samples(_sample())
    result = await _service(samples).apply_sample_action_for_user(
        user_id="user-1",
        dataset_id="fdset-1",
        sample_id="sample-1",
        action="rebuild",
        expected_revision_id="revision-1",
        reason="核对文献 B 的图注",
        idempotency_key="action-1",
    )

    assert result.status == "pending"
    assert result.generation == 2
    assert result.confirmed_revision_id is None
    job = samples.calls[0]["job"]
    assert job.payload["review_note"] == "核对文献 B 的图注"
    assert job.payload["generation"] == 2


async def test_service_surfaces_concurrent_generation_change() -> None:
    class _RacingSamples(_Samples):
        async def apply_action(self, **kwargs):
            self.sample = replace(self.sample, generation=self.sample.generation + 1)
            return await super().apply_action(**kwargs)

    samples = _RacingSamples(_sample())
    with pytest.raises(FeedbackDatasetConflict, match="sample_revision_stale"):
        await _service(samples).apply_sample_action_for_user(
            user_id="user-1", dataset_id="fdset-1", sample_id="sample-1",
            action="discard", expected_revision_id="revision-1", reason=None,
            idempotency_key="action-1",
        )


def test_action_state_machine_and_digest() -> None:
    ensure_action_allowed("needs_input", "rebuild")
    ensure_action_allowed("discarded", "restore")
    with pytest.raises(ValueError, match="sample_action_not_allowed"):
        ensure_action_allowed("confirmed", "restore")
    assert sample_action_digest(action="rebuild", expected_revision_id="rev", reason=" note ") == sample_action_digest(
        action="rebuild", expected_revision_id="rev", reason="note"
    )
