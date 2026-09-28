from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from controllers.feedback import datasets
from controllers.schemas.datasets import DatasetSnapshotCreateRequest
from domain.feedback import DatasetSnapshot


def _request(service, user_id: str = "user-1"):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(dataset_snapshot_service=service)),
        state=SimpleNamespace(current_user={"user_id": user_id}),
    )


def _snapshot() -> DatasetSnapshot:
    return DatasetSnapshot(
        dataset_id="dataset-1",
        owner_id="user-1",
        collection_id="collection-1",
        dataset_type="evaluation",
        rows=(
            {
                "record_type": "evaluation",
                "input": "Question",
                "reference": "Answer",
                "evidence": [],
                "criteria": [],
            },
        ),
        exclusions=(),
        provenance={"items": []},
        manifest={"empty": False, "schema_version": "feedback-dataset.v3"},
        manifest_digest="a" * 64,
        provenance_digest="b" * 64,
        content_digest="c" * 64,
        created_at="2026-09-24T00:00:00+00:00",
    )


class _Service:
    def __init__(self):
        self.snapshot = _snapshot()

    async def create_for_user(self, **kwargs):
        assert kwargs["owner_id"] == "user-1"
        assert "paper_families" not in kwargs
        assert vars(kwargs["selections"][0]) == {"case_id": "case-1"}
        return self.snapshot

    async def list_for_user(self, **kwargs):
        return (self.snapshot,)

    async def read_for_user(self, **kwargs):
        if kwargs["dataset_id"] != self.snapshot.dataset_id:
            raise FileNotFoundError("dataset snapshot not found")
        return self.snapshot

    async def jsonl_for_user(self, **kwargs):
        return self.snapshot, b'{"record_type":"evaluation","split":"eval"}\n'


def test_dataset_routes_create_list_detail_and_download() -> None:
    service = _Service()
    request = _request(service)
    payload = DatasetSnapshotCreateRequest(
        collection_id="collection-1",
        dataset_type="evaluation",
        items=[{"case_id": "case-1"}],
    )
    created = asyncio.run(datasets.create_dataset_snapshot(payload, request))
    assert created.dataset_id == "dataset-1"
    listing = asyncio.run(
        datasets.list_dataset_snapshots(
            request, collection_id="collection-1", limit=50, offset=0
        )
    )
    assert listing.items[0].manifest_digest == "a" * 64
    detail = asyncio.run(datasets.get_dataset_snapshot("dataset-1", request))
    assert detail.row_count == 1
    response = asyncio.run(datasets.download_dataset_snapshot("dataset-1", request))
    assert response.media_type == "application/x-ndjson"
    assert response.body.endswith(b"\n")


def test_dataset_route_maps_missing_snapshot_to_404() -> None:
    class Missing(_Service):
        async def read_for_user(self, **kwargs):
            raise FileNotFoundError("dataset snapshot not found")

    with pytest.raises(HTTPException) as error:
        asyncio.run(datasets.get_dataset_snapshot("missing", _request(Missing())))
    assert error.value.status_code == 404


@pytest.mark.parametrize("extra", [
    {"paper_families": {"doc": "family"}},
    {"items": [{"case_id": "case-1", "split": "eval"}]},
])
def test_creation_rejects_retired_experiment_fields(extra) -> None:
    with pytest.raises(ValidationError):
        DatasetSnapshotCreateRequest.model_validate({
            "collection_id": "collection-1", "dataset_type": "evaluation",
            "items": [{"case_id": "case-1"}], **extra,
        })
