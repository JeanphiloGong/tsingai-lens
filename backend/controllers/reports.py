from __future__ import annotations

from fastapi import APIRouter, Query

from application import report_service
from controllers.schemas.report import (
    ReportCommunityDetailResponse,
    ReportCommunityListResponse,
    ReportPatternsResponse,
)

router = APIRouter(tags=["reports"])


@router.get(
    "/collections/{collection_id}/reports/communities",
    response_model=ReportCommunityListResponse,
    summary="列出社区报告",
)
async def list_community_reports(
    collection_id: str,
    level: int | None = Query(default=2, description="社区层级"),
    limit: int = Query(default=50, ge=1, le=200, description="返回数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    min_size: int = Query(default=0, ge=0, description="最小社区规模过滤"),
    sort: str | None = Query(default="rating", description="排序字段（rating/size）"),
) -> ReportCommunityListResponse:
    return report_service.list_community_reports(
        collection_id=collection_id,
        level=level,
        limit=limit,
        offset=offset,
        min_size=min_size,
        sort=sort,
    )


@router.get(
    "/collections/{collection_id}/reports/communities/{community_id}",
    response_model=ReportCommunityDetailResponse,
    summary="社区报告详情",
)
async def get_community_report_detail(
    collection_id: str,
    community_id: str,
    level: int | None = Query(default=None, description="指定社区层级"),
    entity_limit: int = Query(default=20, ge=1, le=200, description="实体返回数量"),
    relationship_limit: int = Query(
        default=20, ge=1, le=200, description="关系返回数量"
    ),
    document_limit: int = Query(default=20, ge=1, le=200, description="文档返回数量"),
) -> ReportCommunityDetailResponse:
    return report_service.get_community_report_detail(
        collection_id=collection_id,
        community_id=community_id,
        level=level,
        entity_limit=entity_limit,
        relationship_limit=relationship_limit,
        document_limit=document_limit,
    )


@router.get(
    "/collections/{collection_id}/reports/patterns",
    response_model=ReportPatternsResponse,
    summary="社区规律概览",
)
async def list_patterns(
    collection_id: str,
    level: int | None = Query(default=2, description="社区层级"),
    limit: int = Query(default=10, ge=1, le=50, description="返回数量"),
    sort: str | None = Query(default="rating", description="排序字段（rating/size）"),
) -> ReportPatternsResponse:
    return report_service.list_patterns(
        collection_id=collection_id,
        level=level,
        limit=limit,
        sort=sort,
    )
