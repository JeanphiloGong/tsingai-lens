from __future__ import annotations

from pydantic import BaseModel, Field

from controllers.schemas.core.comparisons import ComparisonAssessmentResponse


class ComparableResultBindingResponse(BaseModel):
    """Context bindings attached to one comparable result."""

    variant_id: str | None = Field(default=None, description="样品变体 ID")
    baseline_id: str | None = Field(default=None, description="baseline ID")
    test_condition_id: str | None = Field(default=None, description="测试条件 ID")


class ComparableResultNormalizedContextResponse(BaseModel):
    """Normalized comparison context for one semantic unit."""

    material_system_normalized: str = Field(..., description="标准化材料体系")
    process_normalized: str | None = Field(default=None, description="标准化工艺")
    baseline_normalized: str | None = Field(default=None, description="标准化 baseline")
    test_condition_normalized: str | None = Field(default=None, description="标准化测试条件")


class ComparableResultAxisResponse(BaseModel):
    """Comparison axis binding for one semantic unit."""

    axis_name: str | None = Field(default=None, description="比较轴名称")
    axis_value: str | float | int | None = Field(default=None, description="比较轴取值")
    axis_unit: str | None = Field(default=None, description="比较轴单位")


class ComparableResultValueResponse(BaseModel):
    """Normalized result value payload for one semantic unit."""

    property_normalized: str = Field(..., description="标准化性质指标")
    result_type: str = Field(..., description="结果类型")
    numeric_value: float | None = Field(default=None, description="数值结果")
    unit: str | None = Field(default=None, description="结果单位")
    summary: str = Field(..., description="结果摘要")
    statistic_type: str | None = Field(default=None, description="统计值类型")
    uncertainty: str | None = Field(default=None, description="不确定性说明")


class ComparableResultEvidenceTraceResponse(BaseModel):
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


class ComparableResultCollectionOverlayResponse(BaseModel):
    """Current collection-scoped overlay attached to one corpus comparable result."""

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


class ComparableResultCorpusItemResponse(BaseModel):
    """Corpus comparable-result retrieval item."""

    comparable_result_id: str = Field(..., description="comparable result ID")
    source_result_id: str = Field(..., description="来源 measurement result ID")
    source_document_id: str = Field(..., description="来源文档 ID")
    binding: ComparableResultBindingResponse = Field(..., description="上下文绑定")
    normalized_context: ComparableResultNormalizedContextResponse = Field(
        ...,
        description="标准化比较上下文",
    )
    axis: ComparableResultAxisResponse = Field(..., description="比较轴")
    value: ComparableResultValueResponse = Field(..., description="结果值")
    evidence: ComparableResultEvidenceTraceResponse = Field(..., description="证据追踪")
    variant_label: str | None = Field(default=None, description="样品标签")
    baseline_reference: str | None = Field(default=None, description="baseline 原始引用")
    result_source_type: str | None = Field(default=None, description="结果来源类型")
    epistemic_status: str = Field(..., description="语义层认识论状态")
    normalization_version: str = Field(..., description="标准化版本")
    observed_collection_ids: list[str] = Field(
        default_factory=list,
        description="该 comparable result 当前被哪些 collection 观测到",
    )
    collection_overlays: list[ComparableResultCollectionOverlayResponse] = Field(
        default_factory=list,
        description="附着在 comparable result 上的 current collection overlays",
    )


class ComparableResultCorpusListResponse(BaseModel):
    """Corpus comparable-result list payload."""

    collection_id: str | None = Field(
        default=None,
        description="可选 collection filter；缺省表示 corpus-wide scan",
    )
    total: int = Field(..., description="总条数")
    count: int = Field(..., description="返回条数")
    items: list[ComparableResultCorpusItemResponse] = Field(
        default_factory=list,
        description="corpus comparable result 列表",
    )
