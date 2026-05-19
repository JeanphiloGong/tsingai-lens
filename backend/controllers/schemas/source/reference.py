from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SourceReferenceEntryResponse(BaseModel):
    reference_id: str = Field(..., description="引用条目 ID")
    document_id: str = Field(..., description="来源文档 ID")
    raw_reference: str = Field(..., description="原始引用文本")
    reference_index: str | None = Field(default=None, description="论文内引用编号")
    title: str | None = Field(default=None, description="解析出的标题")
    authors_text: str | None = Field(default=None, description="解析出的作者文本")
    year: int | None = Field(default=None, description="解析出的年份")
    doi: str | None = Field(default=None, description="解析出的 DOI")
    source_block_id: str | None = Field(default=None, description="引用条目来源 block")
    page: int | None = Field(default=None, description="引用条目页码")
    confidence: float = Field(default=0.0, description="引用解析置信度")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SourceReferenceMentionResponse(BaseModel):
    mention_id: str = Field(..., description="正文 citation mention ID")
    document_id: str = Field(..., description="来源文档 ID")
    reference_id: str | None = Field(default=None, description="匹配到的引用条目 ID")
    citation_marker: str = Field(..., description="正文 citation marker")
    context_text: str = Field(..., description="citation 附近正文上下文")
    source_block_id: str | None = Field(default=None, description="正文来源 block")
    page: int | None = Field(default=None, description="正文页码")
    char_start: int | None = Field(default=None, description="block 内起始字符")
    char_end: int | None = Field(default=None, description="block 内结束字符")
    confidence: float = Field(default=0.0, description="mention 解析置信度")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SourceReferenceResolutionResponse(BaseModel):
    resolution_id: str = Field(..., description="外部元数据解析 ID")
    reference_id: str = Field(..., description="引用条目 ID")
    provider: str = Field(..., description="解析来源")
    status: str = Field(..., description="解析状态")
    resolved_title: str | None = Field(default=None, description="解析标题")
    resolved_authors_text: str | None = Field(default=None, description="解析作者文本")
    resolved_year: int | None = Field(default=None, description="解析年份")
    resolved_venue: str | None = Field(default=None, description="解析期刊/会议")
    resolved_doi: str | None = Field(default=None, description="解析 DOI")
    resolved_url: str | None = Field(default=None, description="解析 URL")
    open_access_url: str | None = Field(default=None, description="开放访问 URL")
    confidence: float = Field(default=0.0, description="解析置信度")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SourceReferenceCandidateResponse(BaseModel):
    candidate_id: str = Field(..., description="候选引用文献 ID")
    reference_id: str = Field(..., description="引用条目 ID")
    status: str = Field(..., description="候选状态")
    relevance_score: float = Field(default=0.0, description="相关性分数")
    relevance_reason: str | None = Field(default=None, description="相关性说明")
    cited_by_document_id: str | None = Field(default=None, description="引用它的文档 ID")
    mention_count: int = Field(default=0, description="正文引用次数")
    representative_context: str | None = Field(default=None, description="代表性上下文")
    resolved_doi: str | None = Field(default=None, description="解析 DOI")
    resolved_url: str | None = Field(default=None, description="解析 URL")
    open_access_url: str | None = Field(default=None, description="开放访问 URL")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SourceReferenceSummaryResponse(BaseModel):
    collection_id: str = Field(..., description="集合 ID")
    entry_count: int = Field(default=0, description="引用条目数量")
    mention_count: int = Field(default=0, description="正文 citation mention 数量")
    resolution_count: int = Field(default=0, description="外部解析数量")
    candidate_count: int = Field(default=0, description="候选引用文献数量")


class SourceReferenceSetResponse(SourceReferenceSummaryResponse):
    entries: list[SourceReferenceEntryResponse] = Field(
        default_factory=list,
        description="引用条目",
    )
    mentions: list[SourceReferenceMentionResponse] = Field(
        default_factory=list,
        description="正文 citation mentions",
    )
    resolutions: list[SourceReferenceResolutionResponse] = Field(
        default_factory=list,
        description="外部解析结果",
    )
    candidates: list[SourceReferenceCandidateResponse] = Field(
        default_factory=list,
        description="候选引用文献",
    )
