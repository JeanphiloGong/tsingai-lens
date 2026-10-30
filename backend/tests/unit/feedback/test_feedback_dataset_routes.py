from __future__ import annotations

from domain.feedback.sample_revision import SftRevisionContent

from dataclasses import replace, asdict


import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from application.feedback.dataset_export_service import DatasetExportError
from controllers.feedback import feedback_dataset_routes as task_datasets
from controllers.feedback.task_dataset_schemas import (
    SampleConfirmRequest,
    SampleRevisionUpdateRequest,
    TaskDatasetCreateRequest,
)
from domain.feedback import (
    Dataset,
    DatasetSample,
    FeedbackCase,
    SampleRevision,
    content_digest_for,
)
from main import create_app
from repositories.feedback_dataset_repository import StoredDataset


def _request(service, user_id: str = "user-1"):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(feedback_dataset_service=service)),
        state=SimpleNamespace(current_user={"user_id": user_id}),
    )


def _dataset() -> Dataset:
    return Dataset(
        dataset_id="fdset_1",
        collection_id="collection-1",
        name="SFT",
        task_type="sft",
        construction_spec={},
        spec_version=1,
        created_by="user-1",
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
    content = SftRevisionContent(
        schema_version="literature-sft.v1",
        messages=({"role": "user", "content": "比较 A、B。"},),
        context=({"document_title": "文献 A", "text": "原文"},),
        target="候选回答",
        evidence=({"document_title": "文献 A", "text": "原文"},),
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

    async def list_records_for_user(self, **kwargs):
        return (await self.read_record_for_user(dataset_id="fdset_1"),)

    async def read_record_for_user(self, **kwargs):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return StoredDataset(await self.read_for_user(**kwargs), now, now)

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
        return replace(
            _sample(),
            status="confirmed",
            confirmed_revision_id="revision-1",
            confirmed_by="user-1",
            confirmed_at="2026-09-29T01:00:00+00:00",
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


def test_export_preview_maps_stale_source_to_conflict() -> None:
    class ExportService:
        async def preview_for_user(self, **kwargs):
            raise DatasetExportError("sample_source_stale")

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(feedback_dataset_export_service=ExportService())
        ),
        state=SimpleNamespace(current_user={"user_id": "user-1"}),
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            task_datasets.preview_feedback_dataset_export(
                "fdset_1", request, payload=None
            )
        )
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "sample_source_stale"


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
            from domain.feedback import DatasetSample
            from repositories.feedback_dataset_sample_repository import (
                CollectedDatasetSample,
            )

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

    from controllers.feedback.task_dataset_schemas import DatasetCollectionRequest

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
        "content": json.loads(json.dumps(asdict(_revision().content))),
    })
    response = asyncio.run(task_datasets.update_dataset_sample(
        "fdset_1", "sample-1", payload, _request(Service()),
    ))
    assert response.status == "needs_confirmation"


@pytest.mark.parametrize(
    ("schema_version", "task_fields"),
    [
        ("literature-sft.v1", {"target": "人工回答"}),
        (
            "literature-preference.v1",
            {"response_a": "候选回答 A", "response_b": "候选回答 B"},
        ),
        (
            "literature-evaluation.v1",
            {"reference": "参考回答", "criteria": ["引用与原文一致"]},
        ),
    ],
)
def test_sample_update_rejects_missing_message_content_before_write(
    schema_version, task_fields, monkeypatch,
) -> None:
    service = SimpleNamespace(update_sample=AsyncMock(return_value=_sample()))
    app = FastAPI()
    app.include_router(task_datasets.feedback_dataset_router, prefix="/api/v1")
    app.state.feedback_dataset_service = service
    monkeypatch.setattr(
        task_datasets, "current_user_id", AsyncMock(return_value="user-1")
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            "/api/v1/feedback-datasets/fdset_1/samples/sample-1",
            json={
                "expected_revision_id": "revision-1",
                "content": {
                    "schema_version": schema_version,
                    "messages": [{"role": "user"}],
                    "context": [{"document_title": "文献 A", "text": "原文"}],
                    "evidence": [{"document_title": "文献 A", "text": "原文"}],
                    **task_fields,
                },
            },
        )

    assert response.status_code == 422
    assert any(
        error["loc"][-3:] == ["messages", 0, "content"] and error["type"] == "missing"
        for error in response.json()["detail"]
    )
    service.update_sample.assert_not_awaited()


@pytest.mark.parametrize("variant", [
    {"schema_version": "literature-sft.v1", "target": "有来源的回答"},
    {
        "schema_version": "literature-preference.v1",
        "response_a": "保留测量条件",
        "response_b": "忽略测量条件",
    },
    {
        "schema_version": "literature-evaluation.v1",
        "reference": "原文测量结果",
        "criteria": ["保留来源和条件"],
    },
])
def test_sample_revision_rejects_missing_message_content_before_writing(variant) -> None:
    app = FastAPI()
    service = SimpleNamespace(update_sample=AsyncMock(return_value=_sample()))
    app.state.feedback_dataset_service = service

    @app.middleware("http")
    async def authenticate(request, call_next):
        request.state.current_user = {"user_id": "user-1"}
        return await call_next(request)

    app.include_router(task_datasets.feedback_dataset_router, prefix="/api/v1")
    excerpt = {"document_title": "Ti-6Al-4V LPBF", "text": "原文测量条件"}
    content = {
        **variant,
        "messages": [{"role": "user"}],
        "context": [excerpt],
        "evidence": [excerpt],
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            "/api/v1/feedback-datasets/fdset_1/samples/sample-1",
            json={"expected_revision_id": "revision-1", "content": content},
        )
        assert response.status_code == 422, response.text
        service.update_sample.assert_not_awaited()

        content["messages"][0]["content"] = "比较文献中的孔隙率。"
        response = client.patch(
            "/api/v1/feedback-datasets/fdset_1/samples/sample-1",
            json={"expected_revision_id": "revision-1", "content": content},
        )
        assert response.status_code == 200, response.text
        service.update_sample.assert_awaited_once()
