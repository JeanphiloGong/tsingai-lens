from __future__ import annotations

from fastapi import APIRouter, HTTPException

from application.mock.lens_v1_service import lens_v1_mock_service
from controllers.schemas.workspace import WorkspaceOverviewResponse
from application.collections.service import CollectionService
from application.indexing.task_service import TaskService
from application.workspace.artifact_registry_service import ArtifactRegistryService
from application.workspace.service import WorkspaceService

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
    if lens_v1_mock_service.is_enabled() and lens_v1_mock_service.is_mock_collection(collection_id):
        return WorkspaceOverviewResponse(**lens_v1_mock_service.get_workspace(collection_id))
    try:
        payload = workspace_service.get_workspace_overview(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkspaceOverviewResponse(**payload)
