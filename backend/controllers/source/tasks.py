from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from controllers.schemas.source.task import (
    DocumentPreparationRequest,
    TaskListResponse,
    TaskResponse,
)

router = APIRouter(tags=["tasks"])


@router.post(
    "/collections/{collection_id}/documents/{document_id}/preparation",
    response_model=TaskResponse,
    summary="Prepare one collection document",
)
async def prepare_collection_document(
    collection_id: str,
    document_id: str,
    payload: DocumentPreparationRequest,
    request: Request,
) -> TaskResponse:
    try:
        task = await request.app.state.document_preparation_service.queue_document(
            collection_id,
            document_id,
            mode=payload.mode,
            request_id=getattr(request.state, "request_id", None),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskResponse(**task)


@router.get(
    "/collections/{collection_id}/tasks",
    response_model=TaskListResponse,
    summary="List collection task history",
)
async def list_collection_tasks(
    collection_id: str,
    request: Request,
    status: str | None = Query(default=None, description="Filter by task status"),
    limit: int = Query(default=20, ge=1, le=200, description="Number to return"),
    offset: int = Query(default=0, ge=0, description="Result offset"),
) -> TaskListResponse:
    try:
        await request.app.state.collection_service.get_collection(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    items = [
        TaskResponse(**record)
        for record in await request.app.state.task_service.list_tasks(
            collection_id=collection_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    ]
    return TaskListResponse(collection_id=collection_id, count=len(items), items=items)


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="Get task status")
async def get_task(task_id: str, request: Request) -> TaskResponse:
    try:
        record = await request.app.state.task_service.get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaskResponse(**record)
