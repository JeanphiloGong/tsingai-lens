from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from application.core.comparison_service import (
    ComparableResultNotFoundError,
    ComparisonRowsNotReadyError,
    ComparisonService,
)
from controllers.schemas.core.comparable_results import (
    ComparableResultCorpusItemResponse,
    ComparableResultCorpusListResponse,
)

router = APIRouter(tags=["comparable-results"])
comparison_service = ComparisonService()


def _comparable_results_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "comparable_results_not_ready",
        "message": "The collection does not have comparable results yet. Finish indexing first.",
        "collection_id": collection_id,
    }


@router.get(
    "/comparable-results",
    response_model=ComparableResultCorpusListResponse,
    summary="按 corpus 读取 comparable results",
)
async def list_comparable_results(
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
    source_document_id: Annotated[
        str | None, Query(description="按来源文档筛选")
    ] = None,
    collection_id: Annotated[
        str | None, Query(description="限定到一个 collection 的 current scope")
    ] = None,
) -> ComparableResultCorpusListResponse:
    try:
        payload = comparison_service.list_corpus_comparable_results(
            offset=offset,
            limit=limit,
            material_system_normalized=material_system_normalized,
            property_normalized=property_normalized,
            test_condition_normalized=test_condition_normalized,
            baseline_normalized=baseline_normalized,
            source_document_id=source_document_id,
            collection_id=collection_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ComparisonRowsNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_comparable_results_not_ready_detail(exc.collection_id),
        ) from exc
    return ComparableResultCorpusListResponse(**payload)


@router.get(
    "/comparable-results/{comparable_result_id}",
    response_model=ComparableResultCorpusItemResponse,
    summary="读取一个 corpus comparable result",
)
async def get_comparable_result(
    comparable_result_id: str,
    collection_id: Annotated[
        str | None, Query(description="限定到一个 collection 的 current scope")
    ] = None,
) -> ComparableResultCorpusItemResponse:
    try:
        payload = comparison_service.get_corpus_comparable_result(
            comparable_result_id,
            collection_id=collection_id,
        )
    except ComparableResultNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "comparable_result_not_found",
                "message": str(exc),
                "comparable_result_id": exc.comparable_result_id,
                "collection_id": exc.collection_id,
            },
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ComparisonRowsNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_comparable_results_not_ready_detail(exc.collection_id),
        ) from exc
    return ComparableResultCorpusItemResponse(**payload)
