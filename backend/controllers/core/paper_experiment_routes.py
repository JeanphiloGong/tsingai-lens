"""Read-only HTTP projections for fixed paper-experiment analysis snapshots."""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import quote

from application.core.objectives.analysis import experiment_query_service
from controllers.dependencies.auth import get_current_user_id
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from utils.response import ApiResponse, make_api_response

paper_experiment_router = APIRouter(prefix="/collections", tags=["paper-experiments"])


@paper_experiment_router.get(
    "/{collection_id}/objectives/{objective_id}/experiment-analysis",
    summary="Read experiment-backed analysis records",
    response_model=ApiResponse[dict],
)
async def read_experiment_analysis(
    collection_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    analysis_version: int = Query(..., ge=1),
) -> Response:
    return make_api_response(
        data=await experiment_query_service.export_json(
            collection_id, objective_id, analysis_version, user_id=user_id
        )
    )


@paper_experiment_router.get(
    "/{collection_id}/objectives/{objective_id}/experiment-analysis/export",
    summary="Export fixed experiment-backed analysis data",
    response_model=ApiResponse[dict],
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
async def export_experiment_analysis(
    collection_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    analysis_version: int = Query(..., ge=1),
    format: Literal["json", "csv"] = Query(default="json"),
):
    if format == "csv":
        body = await experiment_query_service.export_csv(
            collection_id, objective_id, analysis_version, user_id=user_id
        )
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    "attachment; "
                    f"filename*=utf-8''{quote(f'experiment-analysis-{objective_id}-{analysis_version}.csv', safe='')}"
                )
            },
        )
    return make_api_response(
        data=await experiment_query_service.export_json(
            collection_id, objective_id, analysis_version, user_id=user_id
        )
    )


__all__ = ["paper_experiment_router"]
