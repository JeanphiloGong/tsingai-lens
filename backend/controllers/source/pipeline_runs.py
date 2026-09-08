from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from controllers.schemas.source.pipeline_run import (
    PipelineRunListResponse,
    PipelineRunResponse,
)


router = APIRouter(tags=["pipeline-runs"])


@router.post(
    "/collections/{collection_id}/documents/{document_id}/preparation",
    response_model=PipelineRunResponse,
    summary="Prepare one collection document",
)
async def prepare_collection_document(
    collection_id: str,
    document_id: str,
    request: Request,
) -> PipelineRunResponse:
    try:
        run = await request.app.state.document_preparation_service.queue_document_preparation(
            collection_id,
            document_id,
            request_id=getattr(request.state, "request_id", None),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PipelineRunResponse(**run)


@router.get(
    "/collections/{collection_id}/pipeline-runs",
    response_model=PipelineRunListResponse,
    summary="List collection pipeline run history",
)
async def list_collection_pipeline_runs(
    collection_id: str,
    request: Request,
    status: str | None = Query(default=None, description="Filter by run status"),
    limit: int = Query(default=20, ge=1, le=200, description="Number to return"),
    offset: int = Query(default=0, ge=0, description="Result offset"),
) -> PipelineRunListResponse:
    try:
        await request.app.state.collection_service.get_collection(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    items = [
        PipelineRunResponse(**record)
        for record in await request.app.state.pipeline_run_service.list_runs(
            collection_id=collection_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    ]
    return PipelineRunListResponse(
        collection_id=collection_id,
        count=len(items),
        items=items,
    )


@router.get(
    "/pipeline-runs/{run_id}",
    response_model=PipelineRunResponse,
    summary="Get pipeline run status",
)
async def get_pipeline_run(run_id: str, request: Request) -> PipelineRunResponse:
    try:
        record = await request.app.state.pipeline_run_service.get_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PipelineRunResponse(**record)
