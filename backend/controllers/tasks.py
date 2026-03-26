from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from controllers.schemas.task import (
    ArtifactStatusResponse,
    IndexTaskCreateRequest,
    TaskResponse,
)
from services.artifact_registry_service import ArtifactRegistryService
from services.collection_service import CollectionService
from services.index_task_runner import IndexTaskRunner
from services.task_service import TaskService

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
