from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ReportCommunitySummary(BaseModel):
    """Summary for a Core-derived pattern group report."""

    report_id: str | None = None
    community_id: int | None = None
    human_readable_id: int | None = None
    level: int | None = None
    parent: int | None = None
    children: list[int] | None = None
    title: str | None = None
    summary: str | None = None
    findings: Any | None = None
    rating: float | None = None
    size: int | None = None


class ReportCommunityListResponse(BaseModel):
    """Response containing Core-derived pattern group summaries."""

    collection_id: str
    level: int | None = None
    total: int
    count: int
    items: list[ReportCommunitySummary]


class ReportEntityItem(BaseModel):
    """Node-like item for a Core-derived pattern group detail."""

    id: str
    title: str
    type: str | None = None
    description: str | None = None
    degree: int | None = None
    frequency: int | None = None


class ReportRelationshipItem(BaseModel):
    """Edge-like item for a Core-derived pattern group detail."""

    id: str
    source: str
    target: str
    description: str | None = None
    weight: float | None = None
    combined_degree: float | None = None
    text_unit_count: int | None = None


class ReportDocumentItem(BaseModel):
    """Document item for community report details."""

    id: str
    title: str | None = None
    creation_date: str | None = None


class ReportCommunityDetailResponse(BaseModel):
    """Core-derived pattern group detail response."""

    collection_id: str
    community_id: int | None = None
    human_readable_id: int | None = None
    level: int | None = None
    parent: int | None = None
    children: list[int] | None = None
    title: str | None = None
    summary: str | None = None
    findings: Any | None = None
    rating: float | None = None
    size: int | None = None
    document_count: int | None = None
    text_unit_count: int | None = None
    entities: list[ReportEntityItem]
    relationships: list[ReportRelationshipItem]
    documents: list[ReportDocumentItem]


class ReportPatternItem(BaseModel):
    """Core-derived pattern summary item."""

    community_id: int | None = None
    title: str | None = None
    summary: str | None = None
    findings: Any | None = None
    rating: float | None = None
    size: int | None = None
    level: int | None = None


class ReportPatternsResponse(BaseModel):
    """Response for pattern summaries."""

    collection_id: str
    level: int | None = None
    total_communities: int
    total_entities: int | None = None
    total_relationships: int | None = None
    total_documents: int | None = None
    count: int
    items: list[ReportPatternItem]
