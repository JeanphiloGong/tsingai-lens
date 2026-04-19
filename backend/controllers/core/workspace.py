from __future__ import annotations

from fastapi import APIRouter, HTTPException

from controllers.schemas.core.workspace import WorkspaceOverviewResponse
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from application.source.artifact_registry_service import ArtifactRegistryService
from application.core.workspace_overview_service import WorkspaceService

router = APIRouter(prefix="/collections", tags=["workspace"])
collection_service = CollectionService()
task_service = TaskService()
artifact_registry_service = ArtifactRegistryService()
workspace_service = WorkspaceService(
    collection_service=collection_service,
    task_service=task_service,
    artifact_registry_service=artifact_registry_service,
)


@router.get("/{collection_id}/workspace", response_model=WorkspaceOverviewResponse, summary="获取集合工作区概览")
async def get_collection_workspace(collection_id: str) -> WorkspaceOverviewResponse:
    try:
        payload = workspace_service.get_workspace_overview(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkspaceOverviewResponse(**payload)
