from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from application.pipeline.collection_build.service import (
    CollectionBuildPreconditionError,
)
from controllers.schemas.source.task import (
    ArtifactStatusResponse,
    BuildTaskCreateRequest,
    TaskListResponse,
    TaskResponse,
)

router = APIRouter(tags=["tasks"])


@router.post(
    "/collections/{collection_id}/tasks/build",
    response_model=TaskResponse,
    summary="Create a collection build task",
)
async def create_build_task(
    collection_id: str,
    payload: BuildTaskCreateRequest,
    request: Request,
) -> TaskResponse:
    try:
        task = await request.app.state.build_pipeline_service.queue_build(
            collection_id,
            mode=payload.mode,
            verbose=payload.verbose,
            additional_context=payload.additional_context,
            request_id=getattr(request.state, "request_id", None),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollectionBuildPreconditionError as exc:
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


@router.get(
    "/tasks/{task_id}/artifacts",
    response_model=ArtifactStatusResponse,
    summary="Get task artifact status",
)
async def get_task_artifacts(task_id: str, request: Request) -> ArtifactStatusResponse:
    try:
        await request.app.state.task_service.get_task(task_id)
        artifacts = await request.app.state.artifact_registry_service.get_for_task(
            task_id
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = {"task_id": task_id, **artifacts}
    return ArtifactStatusResponse(**payload)
