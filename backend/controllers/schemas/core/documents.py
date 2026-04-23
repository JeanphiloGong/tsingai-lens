from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from controllers.schemas.core.comparisons import (
    ComparisonAssessmentResponse,
    ComparisonRowItemResponse,
)


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


class DocumentContentBlockResponse(BaseModel):
    """Viewer-friendly block payload for one document."""

    block_id: str = Field(..., description="block ID")
    block_type: str | None = Field(default=None, description="block 类型")
    heading_path: str | None = Field(default=None, description="heading path")
    heading_level: int = Field(default=0, description="heading level")
    order: int = Field(default=0, description="block 顺序")
    text: str = Field(default="", description="block 文本")
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
    blocks: list[DocumentContentBlockResponse] = Field(default_factory=list, description="block 列表")
    warnings: list[str] = Field(default_factory=list, description="查看器提示")


class DocumentComparisonBindingResponse(BaseModel):
    """Context bindings attached to one comparable result."""

    variant_id: str | None = Field(default=None, description="样品变体 ID")
    baseline_id: str | None = Field(default=None, description="baseline ID")
    test_condition_id: str | None = Field(default=None, description="测试条件 ID")


class DocumentComparisonNormalizedContextResponse(BaseModel):
    """Normalized comparison context for one semantic unit."""

    material_system_normalized: str = Field(..., description="标准化材料体系")
    process_normalized: str | None = Field(default=None, description="标准化工艺")
    baseline_normalized: str | None = Field(default=None, description="标准化 baseline")
    test_condition_normalized: str | None = Field(default=None, description="标准化测试条件")


class DocumentComparisonAxisResponse(BaseModel):
    """Comparison axis binding for one semantic unit."""

    axis_name: str | None = Field(default=None, description="比较轴名称")
    axis_value: str | float | int | None = Field(default=None, description="比较轴取值")
    axis_unit: str | None = Field(default=None, description="比较轴单位")


class DocumentComparisonValueResponse(BaseModel):
    """Normalized result value payload for one semantic unit."""

    property_normalized: str = Field(..., description="标准化性质指标")
    result_type: str = Field(..., description="结果类型")
    numeric_value: float | None = Field(default=None, description="数值结果")
    unit: str | None = Field(default=None, description="结果单位")
    summary: str = Field(..., description="结果摘要")
    statistic_type: str | None = Field(default=None, description="统计值类型")
    uncertainty: str | None = Field(default=None, description="不确定性说明")


class DocumentComparisonEvidenceTraceResponse(BaseModel):
    """Traceability payload for one semantic comparison unit."""

    direct_anchor_ids: list[str] = Field(default_factory=list, description="直接 anchor IDs")
    contextual_anchor_ids: list[str] = Field(default_factory=list, description="上下文 anchor IDs")
    evidence_ids: list[str] = Field(default_factory=list, description="证据 IDs")
    structure_feature_ids: list[str] = Field(default_factory=list, description="结构特征 IDs")
    characterization_observation_ids: list[str] = Field(
        default_factory=list,
        description="表征观察 IDs",
    )
    traceability_status: str = Field(..., description="证据可追溯性状态")


class DocumentCollectionComparableResultResponse(BaseModel):
    """Collection-scoped overlay attached to one comparable result."""

    collection_id: str = Field(..., description="集合 ID")
    comparable_result_id: str = Field(..., description="comparable result ID")
    assessment: ComparisonAssessmentResponse = Field(..., description="collection 语境下的判断")
    epistemic_status: str = Field(..., description="collection 语境下的认识论状态")
    included: bool = Field(default=True, description="当前 collection 是否纳入该结果")
    sort_order: int | None = Field(default=None, description="collection 内排序值")
    policy_family: str = Field(..., description="评估策略族标识")
    policy_version: str = Field(..., description="评估策略版本")
    comparable_result_normalization_version: str = Field(
        ...,
        description="该评估绑定的 comparable result normalization 版本",
    )
    assessment_input_fingerprint: str = Field(..., description="评估输入指纹")
    reassessment_triggers: list[str] = Field(
        default_factory=list,
        description="需要触发重新评估的变更类别",
    )


class DocumentComparisonSemanticItemResponse(BaseModel):
    """Document-first comparable result plus collection overlay."""

    comparable_result_id: str = Field(..., description="comparable result ID")
    source_result_id: str = Field(..., description="来源 measurement result ID")
    source_document_id: str = Field(..., description="来源文档 ID")
    binding: DocumentComparisonBindingResponse = Field(..., description="上下文绑定")
    normalized_context: DocumentComparisonNormalizedContextResponse = Field(
        ...,
        description="标准化比较上下文",
    )
    axis: DocumentComparisonAxisResponse = Field(..., description="比较轴")
    value: DocumentComparisonValueResponse = Field(..., description="结果值")
    evidence: DocumentComparisonEvidenceTraceResponse = Field(..., description="证据追踪")
    variant_label: str | None = Field(default=None, description="样品标签")
    baseline_reference: str | None = Field(default=None, description="baseline 原始引用")
    result_source_type: str | None = Field(default=None, description="结果来源类型")
    epistemic_status: str = Field(..., description="语义层认识论状态")
    normalization_version: str = Field(..., description="标准化版本")
    collection_overlays: list[DocumentCollectionComparableResultResponse] = Field(
        default_factory=list,
        description="附着在 comparable result 上的 collection overlay",
    )
    projected_rows: list[ComparisonRowItemResponse] | None = Field(
        default=None,
        description="按需生成的 row projection",
    )


class DocumentComparisonSemanticListResponse(BaseModel):
    """Document-scoped comparison semantic inspection payload."""

    collection_id: str = Field(..., description="集合 ID")
    document_id: str = Field(..., description="文档 ID")
    total: int = Field(..., description="总条数")
    count: int = Field(..., description="返回条数")
    items: list[DocumentComparisonSemanticItemResponse] = Field(
        default_factory=list,
        description="document 对应的 comparable result 列表",
    )
