from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


EvidenceSourceType = Literal["figure", "table", "method", "text"]
TraceabilityStatus = Literal["direct", "partial", "missing"]
TracebackStatus = Literal["ready", "partial", "unavailable"]


class EvidenceAnchorResponse(BaseModel):
    """Traceable evidence anchor back to source content."""

    anchor_id: str = Field(..., description="锚点 ID")
    document_id: str = Field(..., description="来源文档 ID")
    source_kind: str = Field(..., description="Source artifact 类型")
    source_ref: str = Field(..., description="稳定 Source artifact ID")
    source_type: EvidenceSourceType = Field(..., description="锚点来源类型")
    page: int | None = Field(default=None, description="页码")
    quote: str | None = Field(default=None, description="原文引文")
    deep_link: str | None = Field(default=None, description="前端深链")


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


class EvidenceTracebackResponse(BaseModel):
    """Resolved traceback anchors for a single evidence card."""

    collection_id: str = Field(..., description="集合 ID")
    evidence_id: str = Field(..., description="evidence card ID")
    traceback_status: TracebackStatus = Field(..., description="traceback 可用状态")
    anchors: list[EvidenceAnchorResponse] = Field(default_factory=list, description="可用于查看器的锚点")
