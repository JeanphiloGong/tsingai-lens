from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from controllers.schemas.source.task import (
    ArtifactStatusResponse,
    BuildTaskCreateRequest,
    TaskListResponse,
    TaskResponse,
)
from application.source.collection_service import CollectionService
from application.source.collection_build_task_runner import CollectionBuildTaskRunner
from application.source.task_service import TaskService
from application.source.artifact_registry_service import ArtifactRegistryService

router = APIRouter(tags=["tasks"])
collection_service = CollectionService()
task_service = TaskService()
artifact_registry_service = ArtifactRegistryService()
build_task_runner = CollectionBuildTaskRunner(
    collection_service=collection_service,
    task_service=task_service,
    artifact_registry_service=artifact_registry_service,
)
logger = logging.getLogger(__name__)


@router.post(
    "/collections/{collection_id}/tasks/build",
    response_model=TaskResponse,
    summary="创建集合构建任务",
)
async def create_build_task(
    collection_id: str,
    payload: BuildTaskCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> TaskResponse:
    try:
        collection_service.get_collection(collection_id)
        files = collection_service.list_files(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not files:
        raise HTTPException(status_code=400, detail="集合内没有可构建文件")

    task = task_service.create_task(collection_id=collection_id, task_type="build")
    request_id = getattr(request.state, "request_id", None)
    logger.info(
        "Queued build task task_id=%s collection_id=%s verbose=%s",
        task["task_id"],
        collection_id,
        payload.verbose,
    )
    background_tasks.add_task(
        build_task_runner.run_build_task_blocking,
        task["task_id"],
        collection_id,
        verbose=payload.verbose,
        additional_context=payload.additional_context,
        request_id=request_id,
    )
    return TaskResponse(**task)


@router.get(
    "/collections/{collection_id}/tasks",
    response_model=TaskListResponse,
    summary="列出集合任务历史",
)
async def list_collection_tasks(
    collection_id: str,
    status: str | None = Query(default=None, description="按任务状态过滤"),
    limit: int = Query(default=20, ge=1, le=200, description="返回数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> TaskListResponse:
    try:
        collection_service.get_collection(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    items = [
        TaskResponse(**record)
        for record in task_service.list_tasks(
            collection_id=collection_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    ]
    return TaskListResponse(collection_id=collection_id, count=len(items), items=items)


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="查询任务状态")
async def get_task(task_id: str) -> TaskResponse:
    try:
        record = task_service.get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaskResponse(**record)


@router.get(
    "/tasks/{task_id}/artifacts",
    response_model=ArtifactStatusResponse,
    summary="查询任务产物状态",
)
async def get_task_artifacts(task_id: str) -> ArtifactStatusResponse:
    try:
        task = task_service.get_task(task_id)
        artifacts = artifact_registry_service.get(task["collection_id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = {"task_id": task_id, **artifacts}
    return ArtifactStatusResponse(**payload)
