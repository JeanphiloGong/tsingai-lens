"""Maintained task-specific feedback dataset endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from application.feedback.dataset_service import (
    FeedbackDatasetError,
    FeedbackDatasetService,
)
from controllers.dependencies.auth import current_user_id
from controllers.schemas.task_datasets import (
    TaskDatasetCreateRequest,
    TaskDatasetListResponse,
    TaskDatasetResponse,
)


router = APIRouter(prefix="/feedback-datasets", tags=["feedback-workbench"])


def _service(request: Request) -> FeedbackDatasetService:
    service = getattr(request.app.state, "feedback_dataset_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "feedback_datasets_unavailable",
                "message": "feedback datasets are not configured",
            },
        )
    return service


@router.post("", response_model=TaskDatasetResponse, status_code=status.HTTP_201_CREATED)
async def create_feedback_dataset(
    payload: TaskDatasetCreateRequest,
    request: Request,
) -> TaskDatasetResponse:
    try:
        dataset = await _service(request).create_for_user(
            user_id=await current_user_id(request),
            collection_id=payload.collection_id,
            name=payload.name,
            task_type=payload.task_type,
            construction_spec=payload.construction_spec,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="collection not found") from exc
    except FeedbackDatasetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return TaskDatasetResponse.model_validate(dataset.to_record())


@router.get("", response_model=TaskDatasetListResponse)
async def list_feedback_datasets(
    request: Request,
    collection_id: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TaskDatasetListResponse:
    try:
        datasets = await _service(request).list_for_user(
            user_id=await current_user_id(request),
            collection_id=collection_id,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="collection not found") from exc
    except FeedbackDatasetError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": str(exc)},
        ) from exc
    return TaskDatasetListResponse(
        items=[TaskDatasetResponse.model_validate(item.to_record()) for item in datasets],
        limit=limit,
        offset=offset,
    )


@router.get("/{dataset_id}", response_model=TaskDatasetResponse)
async def get_feedback_dataset(
    dataset_id: str,
    request: Request,
) -> TaskDatasetResponse:
    try:
        dataset = await _service(request).read_for_user(
            user_id=await current_user_id(request),
            dataset_id=dataset_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="dataset not found") from exc
    return TaskDatasetResponse.model_validate(dataset.to_record())


__all__ = ["router"]
