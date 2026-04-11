from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from application.mock.lens_v1_service import lens_v1_mock_service
from controllers.schemas.comparisons import ComparisonRowListResponse

router = APIRouter(prefix="/collections", tags=["comparisons"])


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
    if not lens_v1_mock_service.is_enabled() or not lens_v1_mock_service.is_mock_collection(collection_id):
        raise HTTPException(
            status_code=404,
            detail=f"comparisons not found for collection: {collection_id}",
        )
    payload = lens_v1_mock_service.list_comparisons(
        collection_id,
        offset=offset,
        limit=limit,
    )
    return ComparisonRowListResponse(**payload)
