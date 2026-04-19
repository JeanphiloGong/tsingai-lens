from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from application.core.comparison_service import (
    ComparisonRowNotFoundError,
    ComparisonRowsNotReadyError,
    ComparisonService,
)
from controllers.schemas.core.comparisons import (
    ComparisonRowItemResponse,
    ComparisonRowListResponse,
)

router = APIRouter(prefix="/collections", tags=["comparisons"])
comparison_service = ComparisonService()


def _comparison_rows_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "comparison_rows_not_ready",
        "message": "The collection does not have comparison rows yet. Finish indexing first.",
        "collection_id": collection_id,
    }


@router.get(
    "/{collection_id}/comparisons/{row_id}",
    response_model=ComparisonRowItemResponse,
    summary="读取单个 comparison row",
)
async def get_collection_comparison(
    collection_id: str,
    row_id: str,
) -> ComparisonRowItemResponse:
    try:
        payload = comparison_service.get_comparison_row(collection_id, row_id)
    except ComparisonRowNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "comparison_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "row_id": exc.row_id,
            },
        ) from exc
    except ComparisonRowsNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_comparison_rows_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ComparisonRowItemResponse(**payload)


@router.get(
    "/{collection_id}/comparisons",
    response_model=ComparisonRowListResponse,
    summary="列出 collection 的 comparison rows",
)
async def list_collection_comparisons(
    collection_id: str,
    limit: Annotated[int, Query(ge=1, le=500, description="返回数量")] = 50,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
) -> ComparisonRowListResponse:
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
