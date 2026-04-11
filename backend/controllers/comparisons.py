from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from application.comparisons.service import (
    ComparisonRowsNotReadyError,
    ComparisonService,
)
from application.mock.lens_v1_service import lens_v1_mock_service
from controllers.schemas.comparisons import ComparisonRowListResponse

router = APIRouter(prefix="/collections", tags=["comparisons"])
comparison_service = ComparisonService()


def _comparison_rows_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "comparison_rows_not_ready",
        "message": "The collection does not have comparison rows yet. Finish indexing first.",
        "collection_id": collection_id,
    }


@router.get(
    "/{collection_id}/comparisons",
    response_model=ComparisonRowListResponse,
    summary="列出 collection 的 comparison rows",
)
async def list_collection_comparisons(
    collection_id: str,
    limit: int = Query(default=50, ge=1, le=500, description="返回数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> ComparisonRowListResponse:
    if lens_v1_mock_service.is_enabled() and lens_v1_mock_service.is_mock_collection(collection_id):
        payload = lens_v1_mock_service.list_comparisons(
            collection_id,
            offset=offset,
            limit=limit,
        )
        return ComparisonRowListResponse(**payload)
    try:
        payload = comparison_service.list_comparison_rows(
            collection_id,
            offset=offset,
            limit=limit,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ComparisonRowsNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_comparison_rows_not_ready_detail(exc.collection_id),
        ) from exc
    return ComparisonRowListResponse(**payload)
