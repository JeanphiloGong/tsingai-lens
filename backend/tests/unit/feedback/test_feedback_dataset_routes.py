from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from controllers.feedback import task_datasets
from controllers.schemas.task_datasets import (
    SampleConfirmRequest,
    SampleRevisionUpdateRequest,
    TaskDatasetCreateRequest,
)
from domain.feedback import (
    Dataset,
    DatasetSample,
    FeedbackCase,
    SampleRevision,
    SftRevisionContent,
    content_digest_for,
)
from main import create_app


def _request(service, user_id: str = "user-1"):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(feedback_dataset_service=service)),
        state=SimpleNamespace(current_user={"user_id": user_id}),
    )


def _dataset() -> Dataset:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return Dataset(
        dataset_id="fdset_1",
        collection_id="collection-1",
        name="SFT",
        task_type="sft",
        construction_spec={},
        spec_version=1,
        created_by="user-1",
        created_at=now,
        updated_at=now,
    )


def _sample() -> DatasetSample:
    return DatasetSample(
        sample_id="sample-1",
        dataset_id="fdset_1",
        source_case_id="case-1",
        status="needs_confirmation",
        current_revision_id="revision-1",
        confirmed_revision_id=None,
        generation=1,
        source_digest="a" * 64,
        active_job_id=None,
        missing_reasons=(),
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )


def _revision() -> SampleRevision:
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
        revision_id="revision-1",
        sample_id="sample-1",
        revision_no=1,
        author_kind="worker",
        content=content,
        content_digest=content_digest_for(content),
        input_digest="a" * 64,
        construction_spec_version=1,
        provenance={"source_case_id": "case-1"},
        created_at="2026-09-29T00:00:00+00:00",
        created_by=None,
        job_id="job-1",
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


class _Service:
    async def create_for_user(self, **kwargs):
        assert kwargs["user_id"] == "user-1"
        return _dataset()

    async def list_for_user(self, **kwargs):
        return (_dataset(),)

    async def read_for_user(self, **kwargs):
        if kwargs["dataset_id"] != "fdset_1":
            raise FileNotFoundError("dataset not found")
        return _dataset()

    async def list_samples_for_user(self, **kwargs):
        from application.feedback.dataset_service import DatasetSampleListResult

        return DatasetSampleListResult(
            items=(_sample(),), total=1, limit=kwargs["limit"], offset=kwargs["offset"]
        )

    async def read_sample_for_user(self, **kwargs):
        from application.feedback.dataset_service import DatasetSampleDetail

        return DatasetSampleDetail(
            dataset=_dataset(),
            sample=_sample(),
            current_revision=_revision(),
            confirmed_revision=None,
            source_case=_case(),
        )

    async def update_sample(self, **kwargs):
        return _sample()

    async def confirm_sample(self, **kwargs):
        return DatasetSample(
            **{
                **_sample().to_record(),
                "status": "confirmed",
                "confirmed_revision_id": "revision-1",
                "confirmed_by": "user-1",
                "confirmed_at": "2026-09-29T01:00:00+00:00",
            }
        )


def test_task_dataset_routes_create_list_and_detail() -> None:
    request = _request(_Service())
    payload = TaskDatasetCreateRequest(
        collection_id="collection-1",
        name="SFT",
        task_type="sft",
        construction_spec={},
    )
    created = asyncio.run(task_datasets.create_feedback_dataset(payload, request))
    assert created.dataset_id == "fdset_1"
    listing = asyncio.run(
        task_datasets.list_feedback_datasets(
            request,
            collection_id="collection-1",
            limit=50,
            offset=0,
        )
    )
    assert listing.items[0].task_type == "sft"
    detail = asyncio.run(task_datasets.get_feedback_dataset("fdset_1", request))
    assert detail.collection_id == "collection-1"


def test_legacy_snapshot_routes_are_not_registered_after_d7_cutover() -> None:
    paths = {route.path for route in create_app().routes}

    assert "/api/v1/feedback-datasets" in paths
    assert not any(path.startswith("/api/v1/dataset-snapshots") for path in paths)


def test_task_dataset_route_maps_missing_to_404() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(task_datasets.get_feedback_dataset("missing", _request(_Service())))
    assert error.value.status_code == 404


def test_task_dataset_request_accepts_task_types_and_rejects_extra_fields() -> None:
    preference = TaskDatasetCreateRequest.model_validate({
        "collection_id": "collection-1",
        "name": "Preference",
        "task_type": "preference",
    })
    assert preference.task_type == "preference"
    with pytest.raises(ValidationError):
        TaskDatasetCreateRequest.model_validate({
            "collection_id": "collection-1",
            "name": "SFT",
            "task_type": "sft",
            "owner_id": "user-1",
        })


def test_task_dataset_collection_returns_accepted_operation() -> None:
    class Service(_Service):
        async def collect_cases_for_user(self, **kwargs):
            from application.repositories.feedback_dataset_sample_repository import (
                CollectedDatasetSample,
            )
            from domain.feedback import DatasetSample

            sample = DatasetSample.pending(
                sample_id="sample-1",
                dataset_id="fdset_1",
                source_case_id=kwargs["source_case_ids"][0],
                source_digest="a" * 64,
                active_job_id="job-1",
                now="2026-09-29T00:00:00+00:00",
            )
            return type(
                "Result",
                (),
                {
                    "operation_id": "collect-1",
                    "created_count": 1,
                    "existing_count": 0,
                    "items": (CollectedDatasetSample(sample=sample, job=type("Job", (), {"job_id": "job-1"})()),),
                },
            )()

    from controllers.schemas.task_datasets import DatasetCollectionRequest

    response = asyncio.run(
        task_datasets.collect_feedback_cases(
            "fdset_1",
            DatasetCollectionRequest(source_case_ids=["case-1"]),
            _request(Service()),
        )
    )
    assert response.operation_id == "collect-1"
    assert response.items[0].sample_id == "sample-1"
    assert response.items[0].job_id == "job-1"


def test_task_dataset_sample_routes_keep_revision_and_confirmation_contract() -> None:
    request = _request(_Service())
    listing = asyncio.run(
        task_datasets.list_dataset_samples(
            "fdset_1", request, status_filter="needs_confirmation", limit=50, offset=0
        )
    )
    assert listing.total == 1
    assert listing.items[0].current_revision_id == "revision-1"

    detail = asyncio.run(task_datasets.get_dataset_sample("fdset_1", "sample-1", request))
    assert detail.current_revision is not None
    assert detail.current_revision.content["context"][0]["text"] == "原文"
    assert detail.source_case.question == "比较 A、B。"

    content = {
        "schema_version": "literature-sft.v1",
        "messages": [{"role": "user", "content": "比较 A、B。"}],
        "context": [{"document_title": "文献 A", "text": "原文"}],
        "target": "人工回答",
        "evidence": [{"document_title": "文献 A", "text": "原文"}],
    }
    updated = asyncio.run(
        task_datasets.update_dataset_sample(
            "fdset_1",
            "sample-1",
            SampleRevisionUpdateRequest(expected_revision_id="revision-1", content=content),
            request,
        )
    )
    assert updated.status == "needs_confirmation"

    confirmed = asyncio.run(
        task_datasets.confirm_dataset_sample(
            "fdset_1",
            "sample-1",
            SampleConfirmRequest(expected_revision_id="revision-1"),
            request,
        )
    )
    assert confirmed.status == "confirmed"


def test_first_revision_request_passes_null_revision_and_generation_to_service() -> None:
    class Service(_Service):
        async def update_sample(self, **kwargs):
            assert kwargs["expected_revision_id"] is None
            assert kwargs["expected_generation"] == 3
            assert kwargs["user_id"] == "user-1"
            return _sample()

    payload = SampleRevisionUpdateRequest.model_validate({
        "expected_revision_id": None,
        "expected_generation": 3,
        "content": _revision().content.to_record(),
    })
    response = asyncio.run(task_datasets.update_dataset_sample(
        "fdset_1", "sample-1", payload, _request(Service()),
    ))
    assert response.status == "needs_confirmation"
