from __future__ import annotations

from datetime import datetime, timezone

import pytest
from application.feedback import dataset_service
from application.feedback.dataset_service import FeedbackDatasetError
from domain.feedback import Dataset, FeedbackCase
from domain.feedback.sample_revision import SftRevisionContent
from repositories.feedback_dataset_repository import StoredDataset
from repositories.feedback_dataset_sample_repository import (
    source_digest_for_case,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Collections:
    async def get_collection_for_user(self, collection_id: str, user_id: str):
        if (collection_id, user_id) != ("collection-1", "user-1"):
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id, "owner_user_id": user_id}


class _Repository:
    def __init__(self) -> None:
        self.items: dict[str, Dataset] = {}

    async def create(self, dataset: Dataset) -> StoredDataset:
        self.items[dataset.dataset_id] = dataset
        now = datetime.now(timezone.utc)
        return StoredDataset(dataset=dataset, created_at=now, updated_at=now)

    async def read(self, dataset_id: str) -> Dataset | None:
        return self.items.get(dataset_id)

    async def list_records_for_collection(self, **kwargs):
        return ()


class _Cases:
    def __init__(self, case: FeedbackCase) -> None:
        self.case = case

    async def read_case(self, case_id: str):
        return self.case if case_id == self.case.case_id else None


class _Samples:
    def __init__(self) -> None:
        self.calls = []

    async def collect(self, *, samples, jobs):
        from repositories.feedback_dataset_sample_repository import (
            CollectedDatasetSample,
        )

        self.calls.append((samples, jobs))
        return tuple(
            CollectedDatasetSample(sample, job) for sample, job in zip(samples, jobs)
        )


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


async def test_listing_does_not_create_datasets_or_collect_withdrawn_cases() -> None:
    class ReadOnlyRepository(_Repository):
        async def ensure_system_datasets(self, **kwargs):
            raise AssertionError("a GET must not initialize or enqueue work")

    class UnreadCases:
        async def list_cases(self, **kwargs):
            raise AssertionError("a GET must not scan source cases")

    samples = _Samples()
    dataset_service.FeedbackDatasetRepo = ReadOnlyRepository()
    dataset_service.collection_service = _Collections()
    dataset_service.FeedbackDatasetSampleRepo = samples
    dataset_service.FeedbackCaseRepo = UnreadCases()
    service = dataset_service
    assert (
        await service.list_records_for_user(
            user_id="user-1", collection_id="collection-1"
        )
        == ()
    )
    assert (
        await service.list_records_for_user(
            user_id="user-1", collection_id="collection-1", offset=1
        )
        == ()
    )
    assert samples.calls == []


async def test_collect_reports_source_changed_during_transaction_as_conflict():
    from application.feedback.dataset_service import FeedbackDatasetConflict
    from repositories.feedback_dataset_sample_repository import (
        DatasetSampleRevisionConflict,
    )

    class RacingSamples(_Samples):
        async def collect(self, **kwargs):
            raise DatasetSampleRevisionConflict("sample_source_stale")

    dataset_service.FeedbackDatasetRepo = _Repository()
    dataset_service.collection_service = _Collections()
    dataset_service.FeedbackDatasetSampleRepo = RacingSamples()
    dataset_service.FeedbackCaseRepo = _Cases(_source_case())
    service = dataset_service
    dataset = (
        await service.create_for_user(
            user_id="user-1",
            collection_id="collection-1",
            name="SFT",
            task_type="sft",
            construction_spec={},
        )
    ).dataset
    with pytest.raises(FeedbackDatasetConflict, match="sample_source_stale"):
        await service.collect_cases_for_user(
            user_id="user-1", dataset_id=dataset.dataset_id, source_case_ids=("case-1",)
        )


@pytest.mark.parametrize("excerpt", ["Preheated at 200 C.", "Preheated at 250 C."])
async def test_needs_input_can_save_its_first_complete_human_revision(
    excerpt: str,
) -> None:
    from dataclasses import replace

    from application.feedback.dataset_service import FeedbackDatasetConflict
    from domain.feedback import DatasetSample

    class Samples:
        sample = None
        revision = None

        async def read_sample(self, **kwargs):
            return self.sample

        async def append_human_revision(self, **kwargs):
            self.revision = kwargs["revision"]
            self.sample = replace(
                self.sample,
                status="needs_confirmation",
                current_revision_id=self.revision.revision_id,
            )
            return self.sample

    samples = Samples()
    case = replace(
        _source_case(),
        context_snapshot={
            **_source_case().context_snapshot,
            "inspected_sources": [
                {
                    "document_title": "B",
                    "quote": "Preheated at 200 C.",
                    "source_ref": "source-b",
                }
            ],
        },
    )
    dataset_service.FeedbackDatasetRepo = _Repository()
    dataset_service.collection_service = _Collections()
    dataset_service.FeedbackDatasetSampleRepo = samples
    dataset_service.FeedbackCaseRepo = _Cases(case)
    service = dataset_service
    dataset = (
        await service.create_for_user(
            user_id="user-1",
            collection_id="collection-1",
            name="SFT",
            task_type="sft",
            construction_spec={},
        )
    ).dataset
    samples.sample = replace(
        DatasetSample.pending(
            sample_id="sample-1",
            dataset_id=dataset.dataset_id,
            source_case_id="case-1",
            source_digest=source_digest_for_case(case),
            active_job_id="job-1",
            now=datetime.now(timezone.utc).isoformat(),
        ),
        status="needs_input",
        active_job_id=None,
    )
    content = {
        "schema_version": "literature-sft.v1",
        "messages": [{"role": "user", "content": "Compare A and B."}],
        "context": [{"document_title": "B", "text": excerpt}],
        "target": excerpt,
        "evidence": [{"document_title": "B", "text": excerpt}],
    }
    saved = await service.update_sample(
        user_id="user-1",
        dataset_id=dataset.dataset_id,
        sample_id="sample-1",
        expected_revision_id=None,
        expected_generation=1,
        content=SftRevisionContent(
            schema_version=content["schema_version"],
            messages=tuple(content["messages"]),
            context=tuple(content["context"]),
            target=content["target"],
            evidence=tuple(content["evidence"]),
        ),
    )
    assert saved.status == "needs_confirmation"
    assert samples.revision.revision_no == 1
    assert samples.revision.author_kind == "human"
    assert saved.confirmed_revision_id is None
    record = samples.revision.provenance["evidence_records"][0]
    assert record["annotated_by"] == "user-1"
    if excerpt == "Preheated at 200 C.":
        assert record["source_ref"] == "source-b"
        assert samples.revision.provenance["source_refs"] == ["source-b"]
    else:
        assert record["audit_basis"] == "human_supplied_excerpt"
        assert "source_ref" not in record
        assert samples.revision.provenance["source_refs"] == []
    with pytest.raises(FeedbackDatasetConflict, match="stale"):
        await service.update_sample(
            user_id="user-1",
            dataset_id=dataset.dataset_id,
            sample_id="sample-1",
            expected_revision_id=None,
            expected_generation=1,
            content=SftRevisionContent(
                schema_version=content["schema_version"],
                messages=tuple(content["messages"]),
                context=tuple(content["context"]),
                target=content["target"],
                evidence=tuple(content["evidence"]),
            ),
        )


@pytest.mark.anyio
async def test_create_dataset_has_own_identity_and_fixed_sft_type() -> None:
    repository = _Repository()
    dataset_service.FeedbackDatasetRepo = repository
    dataset_service.collection_service = _Collections()
    service = dataset_service

    dataset = (
        await service.create_for_user(
            user_id="user-1",
            collection_id="collection-1",
            name="  Preheating corrections  ",
            task_type="sft",
            construction_spec={"language": "zh-CN", "source_kinds": ["feedback_case"]},
        )
    ).dataset

    assert dataset.dataset_id.startswith("fdset_")
    assert dataset.dataset_id != "snapshot_123"
    assert dataset.name == "Preheating corrections"
    assert dataset.task_type == "sft"
    assert dataset.spec_version == 1
    assert (
        await service.read_for_user(user_id="user-1", dataset_id=dataset.dataset_id)
        == dataset
    )


async def test_reused_request_rules_cannot_change_saved_spec() -> None:
    repository = _Repository()
    dataset_service.FeedbackDatasetRepo = repository
    dataset_service.collection_service = _Collections()
    service = dataset_service
    spec = {"source_filter": {"kinds": ["feedback_case"]}}
    dataset = (
        await service.create_for_user(
            user_id="user-1",
            collection_id="collection-1",
            name="SFT",
            task_type="sft",
            construction_spec=spec,
        )
    ).dataset
    spec["source_filter"]["kinds"].append("tool_failure")

    saved = await repository.read(dataset.dataset_id)
    assert saved.construction_spec == {"source_filter": {"kinds": ["feedback_case"]}}


@pytest.mark.anyio
async def test_create_allows_task_types_and_rejects_credentials() -> None:
    dataset_service.FeedbackDatasetRepo = _Repository()
    dataset_service.collection_service = _Collections()
    service = dataset_service

    dataset = (
        await service.create_for_user(
            user_id="user-1",
            collection_id="collection-1",
            name="Preference",
            task_type="preference",
            construction_spec={},
        )
    ).dataset
    assert dataset.task_type == "preference"
    with pytest.raises(
        FeedbackDatasetError, match="construction_spec_contains_credential"
    ):
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
    dataset_service.FeedbackDatasetRepo = repository
    dataset_service.collection_service = _Collections()
    service = dataset_service
    await service.create_for_user(
        user_id="user-1",
        collection_id="collection-1",
        name="One",
        task_type="sft",
        construction_spec={},
    )

    with pytest.raises(FileNotFoundError):
        await service.list_records_for_user(
            user_id="user-2", collection_id="collection-1"
        )
    with pytest.raises(FeedbackDatasetError, match="pagination_invalid"):
        await service.list_records_for_user(
            user_id="user-1", collection_id="collection-1", limit=0
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name,task_type,code",
    [
        ("SFT", "unknown", "dataset_task_type_not_available"),
        (" " * 3, "sft", "dataset_name_required"),
        ("x" * 121, "sft", "dataset_name_too_long"),
    ],
)
async def test_dataset_service_rejects_invalid_input(name, task_type, code) -> None:
    dataset_service.FeedbackDatasetRepo = _Repository()
    dataset_service.collection_service = _Collections()
    service = dataset_service
    with pytest.raises(FeedbackDatasetError, match=code):
        await service.create_for_user(
            user_id="user-1",
            collection_id="collection-1",
            name=name,
            task_type=task_type,
            construction_spec={},
        )


@pytest.mark.anyio
async def test_collect_cases_creates_one_pending_sample_job_and_is_explicit() -> None:
    sample_repository = _Samples()
    dataset_service.FeedbackDatasetRepo = _Repository()
    dataset_service.collection_service = _Collections()
    dataset_service.FeedbackDatasetSampleRepo = sample_repository
    dataset_service.FeedbackCaseRepo = _Cases(_source_case())
    service = dataset_service
    dataset = (
        await service.create_for_user(
            user_id="user-1",
            collection_id="collection-1",
            name="SFT",
            task_type="sft",
            construction_spec={},
        )
    ).dataset

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
