from __future__ import annotations

from fastapi import APIRouter, HTTPException

from controllers.schemas.core.workspace import WorkspaceOverviewResponse
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from application.core.workspace_overview_service import WorkspaceService
from infra.persistence.factory import build_collection_repository

router = APIRouter(prefix="/collections", tags=["workspace"])
collection_service = CollectionService(repository=build_collection_repository())
task_service = TaskService()
workspace_service = WorkspaceService(
    collection_service=collection_service,
    task_service=task_service,
)


@router.get("/{collection_id}/workspace", response_model=WorkspaceOverviewResponse, summary="获取集合工作区概览")
async def get_collection_workspace(collection_id: str) -> WorkspaceOverviewResponse:
    try:
        payload = workspace_service.get_workspace_overview(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkspaceOverviewResponse(**payload)
