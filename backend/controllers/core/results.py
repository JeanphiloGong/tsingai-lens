from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from application.core.comparison_service import (
    ComparisonRowsNotReadyError,
    ComparisonService,
    ResultNotFoundError,
)
from controllers.schemas.core.results import ResultItemResponse, ResultListResponse

router = APIRouter(prefix="/collections", tags=["results"])
comparison_service = ComparisonService()


def _results_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "results_not_ready",
        "message": "The collection does not have results yet. Finish indexing first.",
        "collection_id": collection_id,
    }


@router.get(
    "/{collection_id}/results",
    response_model=ResultListResponse,
    summary="列出 collection 的产品向 results",
)
async def list_collection_results(
    collection_id: str,
    limit: Annotated[int, Query(ge=1, le=500, description="返回数量")] = 50,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
    material_system_normalized: Annotated[
        str | None, Query(description="按标准化材料体系筛选")
    ] = None,
    property_normalized: Annotated[
        str | None, Query(description="按标准化性质指标筛选")
    ] = None,
    test_condition_normalized: Annotated[
        str | None, Query(description="按标准化测试条件筛选")
    ] = None,
    baseline_normalized: Annotated[
        str | None, Query(description="按标准化 baseline 筛选")
    ] = None,
    comparability_status: Annotated[
        str | None, Query(description="按 collection 语境下的可比性状态筛选")
    ] = None,
    source_document_id: Annotated[
        str | None, Query(description="按来源文档筛选")
    ] = None,
) -> ResultListResponse:
    try:
        payload = comparison_service.list_collection_results(
            collection_id,
            offset=offset,
            limit=limit,
            material_system_normalized=material_system_normalized,
            property_normalized=property_normalized,
            test_condition_normalized=test_condition_normalized,
            baseline_normalized=baseline_normalized,
            comparability_status=comparability_status,
            source_document_id=source_document_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ComparisonRowsNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_results_not_ready_detail(exc.collection_id),
        ) from exc
    return ResultListResponse(**payload)


@router.get(
    "/{collection_id}/results/{result_id}",
    response_model=ResultItemResponse,
    summary="读取 collection 内单个产品向 result",
)
async def get_collection_result(
    collection_id: str,
    result_id: str,
) -> ResultItemResponse:
    try:
        payload = comparison_service.get_collection_result(collection_id, result_id)
    except ResultNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "result_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "result_id": exc.result_id,
            },
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ComparisonRowsNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_results_not_ready_detail(exc.collection_id),
        ) from exc
    return ResultItemResponse(**payload)
