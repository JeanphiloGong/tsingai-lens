from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


EvidenceSourceType = Literal["figure", "table", "method", "text"]
TraceabilityStatus = Literal["direct", "partial", "missing"]


class EvidenceAnchorResponse(BaseModel):
    """Traceable evidence anchor back to source content."""

    anchor_id: str = Field(..., description="锚点 ID")
    source_type: EvidenceSourceType = Field(..., description="锚点来源类型")
    section_id: str | None = Field(default=None, description="section ID")
    block_id: str | None = Field(default=None, description="block ID")
    snippet_id: str | None = Field(default=None, description="文本片段 ID")
    figure_or_table: str | None = Field(default=None, description="图表引用")
    quote_span: str | None = Field(default=None, description="原文片段")


class ConditionContextResponse(BaseModel):
    """Condition slots kept distinct for comparison and traceback."""

    process: dict[str, Any] = Field(default_factory=dict, description="process/treatment context")
    baseline: dict[str, Any] = Field(default_factory=dict, description="baseline/control context")
    test: dict[str, Any] = Field(default_factory=dict, description="test/measurement context")


class EvidenceCardItemResponse(BaseModel):
    """Claim-centered evidence card."""

    evidence_id: str = Field(..., description="evidence card ID")
    document_id: str = Field(..., description="来源文档 ID")
    collection_id: str = Field(..., description="集合 ID")
    claim_text: str = Field(..., description="主 claim 文本")
    claim_type: str = Field(..., description="claim 类型")
    evidence_source_type: EvidenceSourceType = Field(..., description="主证据来源类型")
    evidence_anchors: list[EvidenceAnchorResponse] = Field(
        default_factory=list,
        description="证据锚点",
    )
    material_system: dict[str, Any] = Field(default_factory=dict, description="材料体系")
    condition_context: ConditionContextResponse = Field(
        default_factory=ConditionContextResponse,
        description="条件上下文",
    )
    confidence: float = Field(..., description="置信度")
    traceability_status: TraceabilityStatus = Field(..., description="追溯状态")


class EvidenceCardListResponse(BaseModel):
    """Collection-scoped evidence card listing."""

    collection_id: str = Field(..., description="集合 ID")
    total: int = Field(..., description="总条数")
    count: int = Field(..., description="返回条数")
    items: list[EvidenceCardItemResponse] = Field(default_factory=list, description="evidence card 列表")
