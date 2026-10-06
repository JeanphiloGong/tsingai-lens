"""Read-only HTTP projections for fixed paper-experiment analysis snapshots."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response


router = APIRouter(prefix="/collections", tags=["paper-experiments"])


@router.get(
    "/{collection_id}/objectives/{objective_id}/experiment-analysis",
    summary="Read experiment-backed analysis records",
)
async def read_experiment_analysis(
    collection_id: str,
    objective_id: str,
    request: Request,
    analysis_version: int = Query(..., ge=1),
) -> dict:
    service = _service(request)
    try:
        return await service.export_json(collection_id, objective_id, analysis_version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/{collection_id}/objectives/{objective_id}/experiment-analysis/export",
    summary="Export fixed experiment-backed analysis data",
)
async def export_experiment_analysis(
    collection_id: str,
    objective_id: str,
    request: Request,
    analysis_version: int = Query(..., ge=1),
    format: str = Query(default="json", pattern="^(json|csv)$"),
):
    service = _service(request)
    try:
        if format == "csv":
            body = await service.export_csv(
                collection_id,
                objective_id,
                analysis_version,
            )
            return Response(
                content=body,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": (
                        "attachment; "
                        f'filename="experiment-analysis-{objective_id}-{analysis_version}.csv"'
                    )
                },
            )
        return await service.export_json(collection_id, objective_id, analysis_version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _service(request: Request):
    service = getattr(request.app.state, "experiment_query_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="experiment analysis projection is unavailable",
        )
    return service


__all__ = ["router"]
