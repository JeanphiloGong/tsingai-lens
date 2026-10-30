from __future__ import annotations

from typing import Annotated

from application.pipeline import pipeline_run_service
from application.source import document_preparation_service
from controllers.dependencies.auth import get_current_user_id
from controllers.schemas.source.pipeline_run import (
    PipelineRunListResponse,
    PipelineRunResponse,
    PipelineRunSummaryResponse,
)
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from utils.response import ApiResponse, make_api_response

pipeline_run_router = APIRouter(tags=["pipeline-runs"])


@pipeline_run_router.post(
    "/collections/{collection_id}/documents/{document_id}/preparation",
    response_model=ApiResponse[PipelineRunResponse],
    summary="Prepare one collection document",
)
async def prepare_collection_document(
    collection_id: str,
    document_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    run = await document_preparation_service.queue_document_preparation(
        collection_id, document_id, user_id=user_id
    )
    return make_api_response(data=PipelineRunResponse(**run))


@pipeline_run_router.get(
    "/collections/{collection_id}/pipeline-runs",
    response_model=ApiResponse[PipelineRunListResponse],
    summary="List collection pipeline run history",
)
async def list_collection_pipeline_runs(
    collection_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    status: str | None = Query(default=None, description="Filter by run status"),
    limit: int = Query(default=20, ge=1, le=200, description="Number to return"),
    offset: int = Query(default=0, ge=0, description="Result offset"),
) -> Response:

    items = [
        PipelineRunSummaryResponse(**record)
        for record in await pipeline_run_service.list_runs(
            collection_id=collection_id,
            status=status,
            limit=limit,
            offset=offset,
            user_id=user_id,
        )
    ]
    return make_api_response(
        data=PipelineRunListResponse(
            collection_id=collection_id,
            count=len(items),
            items=items,
        )
    )


@pipeline_run_router.get(
    "/pipeline-runs/{run_id}",
    response_model=ApiResponse[PipelineRunResponse],
    summary="Get pipeline run status",
)
async def get_pipeline_run(
    run_id: str, user_id: Annotated[str, Depends(get_current_user_id)]
) -> Response:
    record = await pipeline_run_service.get_run(run_id, user_id=user_id)
    return make_api_response(data=PipelineRunResponse(**record))
