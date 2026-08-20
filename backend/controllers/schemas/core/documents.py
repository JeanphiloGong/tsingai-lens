from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DocumentType = Literal["experimental", "review", "mixed", "uncertain"]


class DocumentProfileSummaryResponse(BaseModel):
    """Collection-level rollup derived from document profiles."""

    total_documents: int = 0
    by_doc_type: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class DocumentProfileItemResponse(BaseModel):
    """Single document profile item."""

    document_id: str
    collection_id: str
    title: str | None = None
    source_filename: str | None = None
    doc_type: DocumentType
    parsing_warnings: list[str] = Field(default_factory=list)
    confidence: float


class DocumentProfileListResponse(BaseModel):
    """Collection-scoped document profile listing."""

    collection_id: str
    total: int
    count: int
    summary: DocumentProfileSummaryResponse
    items: list[DocumentProfileItemResponse] = Field(default_factory=list)


class DocumentContentBlockResponse(BaseModel):
    """Viewer-friendly Source block for one document."""

    block_id: str
    block_type: str | None = None
    heading_path: str | None = None
    heading_level: int = 0
    order: int = 0
    text: str = ""
    text_unit_ids: list[str] = Field(default_factory=list)
    page: int | None = None


class DocumentContentResponse(BaseModel):
    """Collection-scoped document viewer payload."""

    collection_id: str
    document_id: str
    title: str | None = None
    source_filename: str | None = None
    content_text: str = ""
    blocks: list[DocumentContentBlockResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentMarkdownSourceMapResponse(BaseModel):
    """Markdown source-map entry pointing back to Source artifacts."""

    markdown_anchor: str
    artifact_type: str
    artifact_id: str
    block_id: str | None = None
    table_id: str | None = None
    figure_id: str | None = None
    block_type: str | None = None
    page: int | None = None
    heading_path: str | None = None
    text_unit_ids: list[str] = Field(default_factory=list)


class DocumentMarkdownResponse(BaseModel):
    """Markdown-first display projection for one parsed document."""

    collection_id: str
    document_id: str
    title: str | None = None
    source_filename: str | None = None
    parser: str | None = None
    markdown: str = ""
    source_map: list[DocumentMarkdownSourceMapResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
