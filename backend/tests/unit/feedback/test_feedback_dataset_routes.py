from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from controllers.feedback import task_datasets
from controllers.schemas.task_datasets import TaskDatasetCreateRequest
from domain.feedback import Dataset


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


def test_task_dataset_route_maps_missing_to_404() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(task_datasets.get_feedback_dataset("missing", _request(_Service())))
    assert error.value.status_code == 404


def test_task_dataset_request_rejects_other_task_types_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TaskDatasetCreateRequest.model_validate({
            "collection_id": "collection-1",
            "name": "Preference",
            "task_type": "preference",
        })
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
