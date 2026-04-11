from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from controllers.schemas.task import (
    ArtifactStatusResponse,
    IndexTaskCreateRequest,
    TaskListResponse,
    TaskResponse,
)
from application.collections.service import CollectionService
from application.indexing.index_task_runner import IndexTaskRunner
from application.indexing.task_service import TaskService
from application.mock.lens_v1_service import lens_v1_mock_service
from application.workspace.artifact_registry_service import ArtifactRegistryService

router = APIRouter(tags=["tasks"])
collection_service = CollectionService()
task_service = TaskService()
artifact_registry_service = ArtifactRegistryService()
index_task_runner = IndexTaskRunner(
    collection_service=collection_service,
    task_service=task_service,
    artifact_registry_service=artifact_registry_service,
)


@router.post(
    "/collections/{collection_id}/tasks/index",
    response_model=TaskResponse,
    summary="创建集合索引任务",
)
async def create_index_task(
    collection_id: str,
    payload: IndexTaskCreateRequest,
    background_tasks: BackgroundTasks,
) -> TaskResponse:
    if lens_v1_mock_service.is_enabled() and lens_v1_mock_service.is_mock_collection(collection_id):
        return TaskResponse(**lens_v1_mock_service.create_index_task(collection_id))
    try:
        collection_service.get_collection(collection_id)
        files = collection_service.list_files(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not files:
        raise HTTPException(status_code=400, detail="集合内没有可索引文件")

    task = task_service.create_task(collection_id=collection_id, task_type="index")
    background_tasks.add_task(
        index_task_runner.run_index_task,
        task["task_id"],
        collection_id,
        payload.method,
        payload.is_update_run,
        payload.verbose,
        payload.additional_context,
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
    if lens_v1_mock_service.is_enabled() and lens_v1_mock_service.is_mock_collection(collection_id):
        items = [
            TaskResponse(**record)
            for record in lens_v1_mock_service.list_tasks(
                collection_id=collection_id,
                status=status,
                limit=limit,
                offset=offset,
            )
        ]
        return TaskListResponse(collection_id=collection_id, count=len(items), items=items)
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
    if lens_v1_mock_service.is_enabled() and lens_v1_mock_service.is_mock_task(task_id):
        return TaskResponse(**lens_v1_mock_service.get_task(task_id))
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
    if lens_v1_mock_service.is_enabled() and lens_v1_mock_service.is_mock_task(task_id):
        return ArtifactStatusResponse(**lens_v1_mock_service.get_task_artifacts(task_id))
    try:
        task = task_service.get_task(task_id)
        artifacts = artifact_registry_service.get(task["collection_id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = {"task_id": task_id, **artifacts}
    return ArtifactStatusResponse(**payload)
