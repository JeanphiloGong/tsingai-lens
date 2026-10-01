"""Dataset snapshot creation and download endpoints."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from application.feedback.dataset_snapshot_service import (
    DatasetSelection,
    DatasetSnapshotError,
    DatasetSnapshotIntegrityError,
    DatasetSnapshotService,
)
from controllers.dependencies.auth import current_user_id

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


router = APIRouter(prefix="/dataset-snapshots", tags=["feedback-workbench"])


def _service(request: Request) -> DatasetSnapshotService:
    service = getattr(request.app.state, "dataset_snapshot_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "dataset_snapshot_unavailable",
                "message": "dataset snapshots are not configured",
            },
        )
    return service


def _response(snapshot: object) -> DatasetSnapshotResponse:
    return DatasetSnapshotResponse.model_validate(snapshot, from_attributes=True)  # type: ignore[attr-defined]


@router.post("", response_model=DatasetSnapshotResponse, status_code=status.HTTP_201_CREATED)
async def create_dataset_snapshot(
    payload: DatasetSnapshotCreateRequest,
    request: Request,
) -> DatasetSnapshotResponse:
    try:
        snapshot = await _service(request).create_for_user(
            owner_id=await current_user_id(request),
            collection_id=payload.collection_id,
            dataset_type=payload.dataset_type,
            selections=tuple(
                DatasetSelection(case_id=item.case_id)
                for item in payload.items
            ),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetSnapshotError as exc:
        code = str(exc).split(":", 1)[0]
        raise HTTPException(
            status_code=422,
            detail={"code": code, "message": str(exc)},
        ) from exc
    return _response(snapshot)


@router.get("", response_model=DatasetSnapshotListResponse)
async def list_dataset_snapshots(
    request: Request,
    collection_id: str | None = Query(default=None, min_length=1, max_length=64),
    dataset_type: str | None = Query(default=None, min_length=1, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DatasetSnapshotListResponse:
    try:
        items = await _service(request).list_for_user(
            owner_id=await current_user_id(request),
            collection_id=collection_id,
            dataset_type=dataset_type,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetSnapshotError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return DatasetSnapshotListResponse(
        items=[
            DatasetSnapshotSummaryResponse.model_validate(
                {
                    "dataset_id": item.dataset_id,
                    "collection_id": item.collection_id,
                    "dataset_type": item.dataset_type,
                    "manifest_digest": item.manifest_digest,
                    "provenance_digest": item.provenance_digest,
                    "content_digest": item.content_digest,
                    "row_count": item.row_count,
                    "excluded_count": item.excluded_count,
                    "is_empty": item.is_empty,
                    "created_at": item.created_at,
                }
            )
            for item in items
        ],
        limit=limit,
        offset=offset,
    )


@router.get("/{dataset_id}/jsonl")
async def download_dataset_snapshot(
    dataset_id: str,
    request: Request,
) -> Response:
    try:
        snapshot, payload = await _service(request).jsonl_for_user(
            owner_id=await current_user_id(request), dataset_id=dataset_id
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": str(exc), "message": "frozen dataset content is inconsistent"},
        ) from exc
    return Response(
        content=payload,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{snapshot.dataset_id}.jsonl"',
            "X-Manifest-Digest": snapshot.manifest_digest,
            "X-Content-Digest": snapshot.content_digest,
        },
    )


@router.get("/{dataset_id}", response_model=DatasetSnapshotResponse)
async def get_dataset_snapshot(
    dataset_id: str,
    request: Request,
) -> DatasetSnapshotResponse:
    try:
        snapshot = await _service(request).read_for_user(
            owner_id=await current_user_id(request), dataset_id=dataset_id
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetSnapshotIntegrityError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": str(exc), "message": "frozen dataset metadata is inconsistent"},
        ) from exc
    return _response(snapshot)


__all__ = ["router"]
