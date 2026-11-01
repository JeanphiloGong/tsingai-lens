from __future__ import annotations

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from controllers.exception_router import project_exception_handler, request_validation_handler, http_exception_handler, general_exception_handler
from exceptions import ProjectException

import asyncio
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.feedback.dataset_export_service import DatasetExportError
from controllers.dependencies.auth import get_current_user_id
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
from domain.feedback.sample_revision import SftRevisionContent
from exceptions import ResourceConflictException, ResourceNotFoundException
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from main import create_app
from pydantic import ValidationError
from repositories.feedback_dataset_repository import StoredDataset


def _request(service, user_id: str = "user-1"):
    task_datasets.dataset_service = service
    return SimpleNamespace(state=SimpleNamespace(current_user={"user_id": user_id}))


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
    async def create_dataset_for_user(self, **kwargs):
        assert kwargs["user_id"] == "user-1"
        now = datetime.now(timezone.utc)
        return StoredDataset(_dataset(), now, now)

    async def list_dataset_records_for_user(self, **kwargs):
        return (await self.read_dataset_record_for_user(dataset_id="fdset_1"),)

    async def read_dataset_record_for_user(self, **kwargs):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return StoredDataset(await self.get_dataset_for_user(**kwargs), now, now)

    async def get_dataset_for_user(self, **kwargs):
        if kwargs["dataset_id"] != "fdset_1":
            raise ResourceNotFoundException("dataset not found")
        return _dataset()

    async def list_dataset_samples_for_user(self, **kwargs):
        from application.feedback.dataset_service import DatasetSampleListResult

        return DatasetSampleListResult(
            items=(_sample(),), total=1, limit=kwargs["limit"], offset=kwargs["offset"]
        )

    async def get_dataset_sample_for_user(self, **kwargs):
        from application.feedback.dataset_service import DatasetSampleDetail

        return DatasetSampleDetail(
            dataset=_dataset(),
            sample=_sample(),
            current_revision=_revision(),
            confirmed_revision=None,
            source_case=_case(),
        )

    async def update_dataset_sample(self, **kwargs):
        return _sample()

    async def confirm_dataset_sample(self, **kwargs):
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
    created = task_datasets.TaskDatasetResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    task_datasets.create_feedback_dataset(
                        payload=payload, user_id=request.state.current_user["user_id"]
                    )
                )
            ).body
        )["data"]
    )
    assert created.dataset_id == "fdset_1"
    listing = task_datasets.TaskDatasetListResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    task_datasets.list_feedback_datasets(
                        user_id=request.state.current_user["user_id"],
                        collection_id="collection-1",
                        limit=50,
                        offset=0,
                    )
                )
            ).body
        )["data"]
    )
    assert listing.items[0].task_type == "sft"
    detail = task_datasets.TaskDatasetResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    task_datasets.get_feedback_dataset(
                        dataset_id="fdset_1",
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    assert detail.collection_id == "collection-1"


def test_legacy_snapshot_routes_are_not_registered_after_d7_cutover() -> None:
    paths = {route.path for route in create_app().routes}

    assert "/api/v1/feedback-datasets" in paths
    assert not any(path.startswith("/api/v1/dataset-snapshots") for path in paths)


def test_task_dataset_route_maps_missing_to_404() -> None:
    with pytest.raises(ResourceNotFoundException) as error:
        task_datasets.TaskDatasetResponse.model_validate(
            json.loads(
                (
                    asyncio.run(
                        task_datasets.get_feedback_dataset(
                            dataset_id="missing",
                            user_id=_request(_Service()).state.current_user["user_id"],
                        )
                    )
                ).body
            )["data"]
        )
    assert error.value.code == 200201


def test_export_preview_maps_stale_source_to_conflict() -> None:
    class ExportService:
        async def preview_dataset_export_for_user(self, **kwargs):
            raise ResourceConflictException(
                "The source changed.", data={"code": "sample_source_stale"}
            )

    task_datasets.dataset_export_service = ExportService()
    with pytest.raises(ResourceConflictException) as error:
        task_datasets.DatasetExportPreviewResponse.model_validate(
            json.loads(
                (
                    asyncio.run(
                        task_datasets.preview_feedback_dataset_export(
                            dataset_id="fdset_1", user_id="user-1", payload=None
                        )
                    )
                ).body
            )["data"]
        )
    assert error.value.code == 200204
    assert error.value.data["code"] == "sample_source_stale"


def test_task_dataset_request_accepts_task_types_and_rejects_extra_fields() -> None:
    preference = TaskDatasetCreateRequest.model_validate(
        {
            "collection_id": "collection-1",
            "name": "Preference",
            "task_type": "preference",
        }
    )
    assert preference.task_type == "preference"
    with pytest.raises(ValidationError):
        TaskDatasetCreateRequest.model_validate(
            {
                "collection_id": "collection-1",
                "name": "SFT",
                "task_type": "sft",
                "owner_id": "user-1",
            }
        )


def test_task_dataset_collection_returns_accepted_operation() -> None:
    class Service(_Service):
        async def collect_dataset_cases_for_user(self, **kwargs):
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
                    "items": (
                        CollectedDatasetSample(
                            sample=sample, job=type("Job", (), {"job_id": "job-1"})()
                        ),
                    ),
                },
            )()

    from controllers.feedback.task_dataset_schemas import DatasetCollectionRequest

    response = task_datasets.DatasetCollectionResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    task_datasets.collect_feedback_cases(
                        dataset_id="fdset_1",
                        payload=DatasetCollectionRequest(source_case_ids=["case-1"]),
                        user_id=_request(Service()).state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    assert response.operation_id == "collect-1"
    assert response.items[0].sample_id == "sample-1"
    assert response.items[0].job_id == "job-1"


def test_task_dataset_sample_routes_keep_revision_and_confirmation_contract() -> None:
    request = _request(_Service())
    listing = task_datasets.DatasetSampleListResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    task_datasets.list_dataset_samples(
                        dataset_id="fdset_1",
                        user_id=request.state.current_user["user_id"],
                        status_filter="needs_confirmation",
                        limit=50,
                        offset=0,
                    )
                )
            ).body
        )["data"]
    )
    assert listing.total == 1
    assert listing.items[0].current_revision_id == "revision-1"

    detail = task_datasets.DatasetSampleDetailResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    task_datasets.get_dataset_sample(
                        dataset_id="fdset_1",
                        sample_id="sample-1",
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
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
    updated = task_datasets.DatasetSampleSummaryResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    task_datasets.update_dataset_sample(
                        dataset_id="fdset_1",
                        sample_id="sample-1",
                        payload=SampleRevisionUpdateRequest(
                            expected_revision_id="revision-1", content=content
                        ),
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    assert updated.status == "needs_confirmation"

    confirmed = task_datasets.DatasetSampleSummaryResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    task_datasets.confirm_dataset_sample(
                        dataset_id="fdset_1",
                        sample_id="sample-1",
                        payload=SampleConfirmRequest(expected_revision_id="revision-1"),
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    assert confirmed.status == "confirmed"


def test_first_revision_request_passes_null_revision_and_generation_to_service() -> (
    None
):
    class Service(_Service):
        async def update_dataset_sample(self, **kwargs):
            assert kwargs["expected_revision_id"] is None
            assert kwargs["expected_generation"] == 3
            assert kwargs["user_id"] == "user-1"
            return _sample()

    payload = SampleRevisionUpdateRequest.model_validate(
        {
            "expected_revision_id": None,
            "expected_generation": 3,
            "content": json.loads(json.dumps(asdict(_revision().content))),
        }
    )
    response = task_datasets.DatasetSampleSummaryResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    task_datasets.update_dataset_sample(
                        dataset_id="fdset_1",
                        sample_id="sample-1",
                        payload=payload,
                        user_id=_request(Service()).state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
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
    schema_version,
    task_fields,
    monkeypatch,
) -> None:
    service = SimpleNamespace(update_dataset_sample=AsyncMock(return_value=_sample()))
    app = FastAPI()
    app.add_exception_handler(ProjectException, project_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    app.include_router(task_datasets.feedback_dataset_router, prefix="/api/v1")
    monkeypatch.setattr(task_datasets, "dataset_service", service)
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

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

    assert response.status_code == 200
    assert response.json()["code"] == 200100
    assert any(
        error["loc"][-3:] == ["messages", 0, "content"] and error["type"] == "missing"
        for error in response.json()["data"]["errors"]
    )
    service.update_dataset_sample.assert_not_awaited()


@pytest.mark.parametrize(
    "variant",
    [
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
    ],
)
def test_sample_revision_rejects_missing_message_content_before_writing(
    variant,
) -> None:
    app = FastAPI()
    app.add_exception_handler(ProjectException, project_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    service = SimpleNamespace(update_dataset_sample=AsyncMock(return_value=_sample()))
    task_datasets.dataset_service = service
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
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
        assert response.status_code == 200
        assert response.json()["code"] == 200100
        service.update_dataset_sample.assert_not_awaited()

        content["messages"][0]["content"] = "比较文献中的孔隙率。"
        response = client.patch(
            "/api/v1/feedback-datasets/fdset_1/samples/sample-1",
            json={"expected_revision_id": "revision-1", "content": content},
        )
        assert response.status_code == 200, response.text
        service.update_dataset_sample.assert_awaited_once()
