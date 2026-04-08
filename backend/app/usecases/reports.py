"""Legacy compatibility wrapper for report use cases."""

from __future__ import annotations

import application.reports as application_reports

from api.schemas import (
    ReportCommunityDetailResponse,
    ReportCommunityListResponse,
    ReportPatternsResponse,
)


def list_community_reports(
    collection_id: str | None,
    level: int | None,
    limit: int,
    offset: int,
    min_size: int,
    sort: str | None,
) -> ReportCommunityListResponse:
    """Delegate to the application-layer reports implementation."""
    return application_reports.list_community_reports(
        collection_id=collection_id,
        level=level,
        limit=limit,
        offset=offset,
        min_size=min_size,
        sort=sort,
    )


def get_community_report_detail(
    collection_id: str | None,
    community_id: str,
    level: int | None,
    entity_limit: int,
    relationship_limit: int,
    document_limit: int,
) -> ReportCommunityDetailResponse:
    """Delegate to the application-layer reports implementation."""
    return application_reports.get_community_report_detail(
        collection_id=collection_id,
        community_id=community_id,
        level=level,
        entity_limit=entity_limit,
        relationship_limit=relationship_limit,
        document_limit=document_limit,
    )


def list_patterns(
    collection_id: str | None,
    level: int | None,
    limit: int,
    sort: str | None,
) -> ReportPatternsResponse:
    """Delegate to the application-layer reports implementation."""
    return application_reports.list_patterns(
        collection_id=collection_id,
        level=level,
        limit=limit,
        sort=sort,
    )


__all__ = [
    "get_community_report_detail",
    "list_community_reports",
    "list_patterns",
]
