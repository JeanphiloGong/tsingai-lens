from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from controllers.schemas.core.workspace import WorkspaceOverviewResponse

router = APIRouter(prefix="/collections", tags=["workspace"])


@router.get("/{collection_id}/workspace", response_model=WorkspaceOverviewResponse, summary="获取集合工作区概览")
async def get_collection_workspace(
    collection_id: str,
    request: Request,
) -> WorkspaceOverviewResponse:
    try:
        payload = request.app.state.workspace_service.get_workspace_overview(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkspaceOverviewResponse(**payload)
