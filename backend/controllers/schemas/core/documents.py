from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DocumentType = Literal["experimental", "review", "mixed", "uncertain"]
ProtocolExtractableStatus = Literal["yes", "partial", "no", "uncertain"]


class DocumentProfileSummaryResponse(BaseModel):
    """Collection-level rollup derived from document profiles."""

    total_documents: int = Field(default=0, description="文档总数")
    by_doc_type: dict[str, int] = Field(default_factory=dict, description="按文档类型统计")
    by_protocol_extractable: dict[str, int] = Field(
        default_factory=dict,
        description="按 protocol suitability 统计",
    )
    warnings: list[str] = Field(default_factory=list, description="集合级提示")


class DocumentProfileItemResponse(BaseModel):
    """Single document profile item."""

    document_id: str = Field(..., description="文档 ID")
    collection_id: str = Field(..., description="集合 ID")
    title: str | None = Field(default=None, description="文档/论文标题；缺失时为 null")
    source_filename: str | None = Field(
        default=None,
        description="源文件名；缺失时为 null",
    )
    doc_type: DocumentType = Field(..., description="文档类型")
    protocol_extractable: ProtocolExtractableStatus = Field(
        ...,
        description="是否适合 protocol 分支",
    )
    protocol_extractability_signals: list[str] = Field(
        default_factory=list,
        description="protocol 判断信号",
    )
    parsing_warnings: list[str] = Field(default_factory=list, description="解析警告")
    confidence: float = Field(..., description="判断置信度")


class DocumentProfileListResponse(BaseModel):
    """Collection-scoped document profile listing."""

    collection_id: str = Field(..., description="集合 ID")
    total: int = Field(..., description="总条数")
    count: int = Field(..., description="返回条数")
    summary: DocumentProfileSummaryResponse = Field(..., description="集合级摘要")
    items: list[DocumentProfileItemResponse] = Field(default_factory=list, description="文档 profile 列表")


class DocumentContentSectionResponse(BaseModel):
    """Viewer-friendly section payload for one document."""

    section_id: str = Field(..., description="section ID")
    heading: str | None = Field(default=None, description="section heading")
    section_type: str | None = Field(default=None, description="section 类型")
    order: int = Field(default=0, description="section 顺序")
    text: str = Field(default="", description="section 文本")
    text_unit_ids: list[str] = Field(default_factory=list, description="相关 text unit IDs")
    start_offset: int | None = Field(default=None, description="文档级起始字符偏移")
    end_offset: int | None = Field(default=None, description="文档级结束字符偏移")


class DocumentContentResponse(BaseModel):
    """Collection-scoped document viewer payload."""

    collection_id: str = Field(..., description="集合 ID")
    document_id: str = Field(..., description="文档 ID")
    title: str | None = Field(default=None, description="文档标题")
    source_filename: str | None = Field(default=None, description="源文件名")
    content_text: str = Field(default="", description="完整文本内容")
    sections: list[DocumentContentSectionResponse] = Field(default_factory=list, description="section 列表")
    warnings: list[str] = Field(default_factory=list, description="查看器提示")
