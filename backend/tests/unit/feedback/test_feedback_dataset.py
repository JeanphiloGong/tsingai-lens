from __future__ import annotations

from datetime import datetime, timezone

import pytest

from application.feedback.dataset_service import (
    FeedbackDatasetError,
    FeedbackDatasetService,
)
from domain.feedback import Dataset
from domain.feedback import FeedbackCase


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Collections:
    async def get_collection_for_user(self, collection_id: str, user_id: str):
        if (collection_id, user_id) != ("collection-1", "user-1"):
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id}


class _Repository:
    def __init__(self) -> None:
        self.items: dict[str, Dataset] = {}

    async def create(self, dataset: Dataset) -> Dataset:
        self.items[dataset.dataset_id] = dataset
        return dataset

    async def read(self, dataset_id: str) -> Dataset | None:
        return self.items.get(dataset_id)

    async def list_for_collection(self, *, collection_id: str, limit: int, offset: int):
        values = [
            item
            for item in self.items.values()
            if item.collection_id == collection_id
        ]
        return tuple(values[offset : offset + limit])


class _Cases:
    def __init__(self, case: FeedbackCase) -> None:
        self.case = case

    async def read_case(self, case_id: str):
        return self.case if case_id == self.case.case_id else None


class _Samples:
    def __init__(self) -> None:
        self.calls = []

    async def collect(self, *, samples, jobs):
        from application.repositories.feedback_dataset_sample_repository import (
            CollectedDatasetSample,
        )

        self.calls.append((samples, jobs))
        return tuple(CollectedDatasetSample(sample, job) for sample, job in zip(samples, jobs))


def _source_case() -> FeedbackCase:
    return FeedbackCase(
        case_id="case-1",
        collection_id="collection-1",
        session_id="session-1",
        anchor_message_id="answer-1",
        source_signal_ids=(),
        analysis_result_ids=(),
        context_snapshot={"question": "Compare A and B."},
        status="needs_annotation",
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


@pytest.mark.anyio
async def test_create_dataset_has_own_identity_and_fixed_sft_type() -> None:
    repository = _Repository()
    service = FeedbackDatasetService(
        repository=repository,
        collection_service=_Collections(),
    )

    dataset = await service.create_for_user(
        user_id="user-1",
        collection_id="collection-1",
        name="  Preheating corrections  ",
        task_type="sft",
        construction_spec={"language": "zh-CN", "source_kinds": ["feedback_case"]},
    )

    assert dataset.dataset_id.startswith("fdset_")
    assert dataset.dataset_id != "snapshot_123"
    assert dataset.name == "Preheating corrections"
    assert dataset.task_type == "sft"
    assert dataset.spec_version == 1
    assert await service.read_for_user(user_id="user-1", dataset_id=dataset.dataset_id) == dataset


@pytest.mark.anyio
async def test_create_allows_task_types_and_rejects_credentials() -> None:
    service = FeedbackDatasetService(
        repository=_Repository(),
        collection_service=_Collections(),
    )

    dataset = await service.create_for_user(
        user_id="user-1",
        collection_id="collection-1",
        name="Preference",
        task_type="preference",
        construction_spec={},
    )
    assert dataset.task_type == "preference"
    with pytest.raises(FeedbackDatasetError, match="construction_spec_contains_credential"):
        await service.create_for_user(
            user_id="user-1",
            collection_id="collection-1",
            name="SFT",
            task_type="sft",
            construction_spec={"provider": {"api_key": "secret"}},
        )


@pytest.mark.anyio
async def test_collection_scope_and_pagination_are_enforced() -> None:
    repository = _Repository()
    service = FeedbackDatasetService(repository=repository, collection_service=_Collections())
    await service.create_for_user(
        user_id="user-1",
        collection_id="collection-1",
        name="One",
        task_type="sft",
        construction_spec={},
    )

    with pytest.raises(FileNotFoundError):
        await service.list_for_user(user_id="user-2", collection_id="collection-1")
    with pytest.raises(FeedbackDatasetError, match="pagination_invalid"):
        await service.list_for_user(user_id="user-1", collection_id="collection-1", limit=0)


def test_dataset_domain_normalizes_name_and_rejects_unknown_type() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="invalid dataset task type"):
        Dataset(
            dataset_id="fdset_1",
            collection_id="collection-1",
            name="SFT",
            task_type="unknown",  # type: ignore[arg-type]
            construction_spec={},
            spec_version=1,
            created_by="user-1",
            created_at=now,
            updated_at=now,
        )


@pytest.mark.anyio
async def test_collect_cases_creates_one_pending_sample_job_and_is_explicit() -> None:
    sample_repository = _Samples()
    service = FeedbackDatasetService(
        repository=_Repository(),
        collection_service=_Collections(),
        sample_repository=sample_repository,
        case_repository=_Cases(_source_case()),
    )
    dataset = await service.create_for_user(
        user_id="user-1",
        collection_id="collection-1",
        name="SFT",
        task_type="sft",
        construction_spec={},
    )

    collected = await service.collect_cases_for_user(
        user_id="user-1",
        dataset_id=dataset.dataset_id,
        source_case_ids=("case-1",),
    )

    assert collected.created_count == 1
    assert collected.existing_count == 0
    assert len(sample_repository.calls) == 1
    sample, job = sample_repository.calls[0][0][0], sample_repository.calls[0][1][0]
    assert sample.status == "pending"
    assert sample.active_job_id == job.job_id
    assert job.job_type == "dataset_sample_build"
    assert job.payload["dataset_id"] == dataset.dataset_id
