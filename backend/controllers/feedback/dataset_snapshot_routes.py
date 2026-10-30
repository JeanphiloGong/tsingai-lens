"""Dataset snapshot creation and download endpoints."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from application.feedback import dataset_snapshot_service
from application.feedback.dataset_snapshot_service import DatasetSelection
from controllers.dependencies.auth import get_current_user_id
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from utils.response import ApiResponse, make_api_response

DatasetTypeLiteral = Literal["evaluation", "sft", "preference"]


class DatasetSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1, max_length=64)


class DatasetSnapshotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_id: str = Field(min_length=1, max_length=64)
    dataset_type: DatasetTypeLiteral
    items: list[DatasetSelectionRequest] = Field(default_factory=list, max_length=500)


class DatasetSnapshotResponse(BaseModel):
    dataset_id: str
    owner_id: str
    collection_id: str
    dataset_type: DatasetTypeLiteral
    rows: list[dict[str, Any]] = Field(default_factory=list)
    exclusions: list[dict[str, Any]] = Field(default_factory=list)
    provenance: dict[str, Any]
    manifest: dict[str, Any]
    manifest_digest: str
    provenance_digest: str
    content_digest: str
    row_count: int
    excluded_count: int
    is_empty: bool
    created_at: str


class DatasetSnapshotSummaryResponse(BaseModel):
    dataset_id: str
    collection_id: str
    dataset_type: DatasetTypeLiteral
    manifest_digest: str
    provenance_digest: str
    content_digest: str
    row_count: int
    excluded_count: int
    is_empty: bool
    created_at: str


class DatasetSnapshotListResponse(BaseModel):
    items: list[DatasetSnapshotSummaryResponse]
    limit: int
    offset: int


dataset_snapshot_router = APIRouter(
    prefix="/dataset-snapshots", tags=["feedback-workbench"]
)


@dataset_snapshot_router.post(
    "", response_model=ApiResponse[DatasetSnapshotResponse], status_code=200
)
async def create_dataset_snapshot(
    payload: DatasetSnapshotCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    snapshot = await dataset_snapshot_service.create_for_user(
        owner_id=user_id,
        collection_id=payload.collection_id,
        dataset_type=payload.dataset_type,
        selections=tuple(
            DatasetSelection(case_id=item.case_id) for item in payload.items
        ),
    )
    return make_api_response(
        data=DatasetSnapshotResponse.model_validate(snapshot, from_attributes=True)
    )


@dataset_snapshot_router.get(
    "", response_model=ApiResponse[DatasetSnapshotListResponse]
)
async def list_dataset_snapshots(
    user_id: Annotated[str, Depends(get_current_user_id)],
    collection_id: str | None = Query(default=None, min_length=1, max_length=64),
    dataset_type: str | None = Query(default=None, min_length=1, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Response:
    items = await dataset_snapshot_service.list_for_user(
        owner_id=user_id,
        collection_id=collection_id,
        dataset_type=dataset_type,
        limit=limit,
        offset=offset,
    )
    return make_api_response(
        data=DatasetSnapshotListResponse(
            items=[
                DatasetSnapshotSummaryResponse.model_validate(
                    item, from_attributes=True
                )
                for item in items
            ],
            limit=limit,
            offset=offset,
        )
    )


@dataset_snapshot_router.get("/{dataset_id}/jsonl")
async def download_dataset_snapshot(
    dataset_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    snapshot, payload = await dataset_snapshot_service.jsonl_for_user(
        owner_id=user_id, dataset_id=dataset_id
    )
    return Response(
        content=payload,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{snapshot.dataset_id}.jsonl"',
            "X-Manifest-Digest": snapshot.manifest_digest,
            "X-Content-Digest": snapshot.content_digest,
        },
    )


@dataset_snapshot_router.get(
    "/{dataset_id}", response_model=ApiResponse[DatasetSnapshotResponse]
)
async def get_dataset_snapshot(
    dataset_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    snapshot = await dataset_snapshot_service.read_for_user(
        owner_id=user_id, dataset_id=dataset_id
    )
    return make_api_response(
        data=DatasetSnapshotResponse.model_validate(snapshot, from_attributes=True)
    )


__all__ = ["dataset_snapshot_router"]
