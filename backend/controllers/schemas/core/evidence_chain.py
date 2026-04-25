from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from controllers.schemas.core.comparisons import ComparabilityStatus


class EvidenceChainMaterialResponse(BaseModel):
    """Material identity used by evidence-chain projections."""

    label: str = Field(..., description="材料标签")
    composition: str | None = Field(default=None, description="成分")
    host_material_system: dict[str, Any] | None = Field(
        default=None,
        description="host material system payload",
    )


class EvidenceChainVariantDossierSummaryResponse(BaseModel):
    """Parent variant dossier context for one or more result chains."""

    variant_id: str | None = Field(default=None, description="样品变体 ID")
    variant_label: str | None = Field(default=None, description="样品变体标签")
    material: EvidenceChainMaterialResponse = Field(..., description="材料信息")
    shared_process_state: dict[str, Any] = Field(
        default_factory=dict,
        description="dossier 共享的工艺或样品状态",
    )
    shared_missingness: list[str] = Field(
        default_factory=list,
        description="影响该 dossier 下所有 chains 的缺失信息",
    )


class EvidenceChainMeasurementResponse(BaseModel):
    """Display-facing measurement summary for a result chain."""

    property: str = Field(..., description="性质指标")
    value: float | None = Field(default=None, description="结果数值")
    unit: str | None = Field(default=None, description="结果单位")
    result_type: str = Field(..., description="结果类型")
    summary: str = Field(..., description="结果摘要")
    statistic_type: str | None = Field(default=None, description="统计值类型")
    uncertainty: str | None = Field(default=None, description="不确定性说明")


class EvidenceChainTestConditionResponse(BaseModel):
    """Chain-local test condition payload."""

    model_config = ConfigDict(populate_by_name=True)

    test_method: str | None = Field(default=None, description="测试方法")
    test_temperature_c: float | None = Field(default=None, description="测试温度 C")
    strain_rate_s_1: float | str | None = Field(
        default=None,
        alias="strain_rate_s-1",
        description="应变速率 s^-1",
    )
    loading_direction: str | None = Field(default=None, description="加载方向")
    sample_orientation: str | None = Field(default=None, description="样品取向")
    environment: str | None = Field(default=None, description="测试环境")
    frequency_hz: float | None = Field(default=None, description="测试频率 Hz")
    specimen_geometry: str | None = Field(default=None, description="试样几何")
    surface_state: str | None = Field(default=None, description="表面状态")


class EvidenceChainBaselineResponse(BaseModel):
    """Baseline binding for a result chain."""

    label: str | None = Field(default=None, description="baseline 标签")
    reference: str | None = Field(default=None, description="baseline 引用")
    baseline_type: str | None = Field(default=None, description="baseline 类型")
    resolved: bool = Field(default=False, description="baseline 是否解析")


class ResultBaselineDetailResponse(EvidenceChainBaselineResponse):
    """Result detail baseline payload."""

    baseline_scope: str | None = Field(default=None, description="baseline scope")


class EvidenceChainAssessmentResponse(BaseModel):
    """Collection-scoped assessment attached to one result chain."""

    comparability_status: ComparabilityStatus = Field(..., description="可比性状态")
    warnings: list[str] = Field(default_factory=list, description="可比性警告")
    basis: list[str] = Field(default_factory=list, description="可比性判断依据")
    missing_context: list[str] = Field(default_factory=list, description="缺失上下文")
    requires_expert_review: bool = Field(default=False, description="是否需要专家复核")
    assessment_epistemic_status: str = Field(..., description="评估认识论状态")


class EvidenceChainValueProvenanceResponse(BaseModel):
    """Value provenance for evidence-chain review."""

    value_origin: str = Field(..., description="reported/derived/estimated")
    source_value_text: str | None = Field(default=None, description="原文数值文本")
    source_unit_text: str | None = Field(default=None, description="原文单位文本")
    derivation_formula: str | None = Field(default=None, description="派生公式")
    derivation_inputs: dict[str, Any] | None = Field(default=None, description="派生输入")


class EvidenceChainTraceResponse(BaseModel):
    """Traceback IDs for one result chain."""

    evidence_ids: list[str] = Field(default_factory=list, description="evidence IDs")
    direct_anchor_ids: list[str] = Field(default_factory=list, description="直接 anchor IDs")
    contextual_anchor_ids: list[str] = Field(
        default_factory=list,
        description="上下文 anchor IDs",
    )
    structure_feature_ids: list[str] = Field(
        default_factory=list,
        description="结构特征 IDs",
    )
    characterization_observation_ids: list[str] = Field(
        default_factory=list,
        description="表征观察 IDs",
    )
    traceability_status: str = Field(..., description="可追溯性状态")


class EvidenceChainResultResponse(BaseModel):
    """One result chain inside a document-side series projection."""

    result_id: str = Field(..., description="产品向 result ID")
    source_result_id: str = Field(..., description="来源 measurement result ID")
    measurement: EvidenceChainMeasurementResponse = Field(..., description="测量值")
    test_condition: EvidenceChainTestConditionResponse = Field(..., description="测试条件")
    baseline: EvidenceChainBaselineResponse = Field(..., description="baseline")
    assessment: EvidenceChainAssessmentResponse = Field(..., description="collection 判断")
    value_provenance: EvidenceChainValueProvenanceResponse = Field(..., description="数值来源")
    evidence: EvidenceChainTraceResponse = Field(..., description="证据链追踪")


class EvidenceChainVaryingAxisResponse(BaseModel):
    """The explicit test-side axis used by a result series."""

    axis_name: str | None = Field(default=None, description="变化轴名称")
    axis_unit: str | None = Field(default=None, description="变化轴单位")


class EvidenceChainSeriesResponse(BaseModel):
    """Sibling result chains under one fixed variant dossier."""

    series_key: str = Field(..., description="series key")
    property_family: str = Field(..., description="性质族")
    test_family: str = Field(..., description="测试族")
    varying_axis: EvidenceChainVaryingAxisResponse = Field(..., description="变化轴")
    chains: list[EvidenceChainResultResponse] = Field(
        default_factory=list,
        description="result chains",
    )


class EvidenceChainVariantDossierResponse(EvidenceChainVariantDossierSummaryResponse):
    """Document-side variant dossier with grouped result series."""

    series: list[EvidenceChainSeriesResponse] = Field(
        default_factory=list,
        description="result series",
    )


class ResultStructureSupportResponse(BaseModel):
    """Structure or characterization support for one result detail."""

    support_id: str = Field(..., description="support ID")
    support_type: str = Field(..., description="support 类型")
    summary: str = Field(..., description="support 摘要")
    condition: dict[str, Any] = Field(default_factory=dict, description="表征条件")


class ResultSeriesSiblingMeasurementResponse(BaseModel):
    """Compact measurement summary for one sibling chain."""

    property: str = Field(..., description="性质指标")
    value: float | None = Field(default=None, description="结果数值")
    unit: str | None = Field(default=None, description="结果单位")


class ResultSeriesSiblingResponse(BaseModel):
    """Sibling result pointer inside result-detail series navigation."""

    result_id: str = Field(..., description="产品向 result ID")
    axis_value: str | float | int | None = Field(default=None, description="轴取值")
    axis_unit: str | None = Field(default=None, description="轴单位")
    measurement: ResultSeriesSiblingMeasurementResponse = Field(..., description="测量摘要")


class ResultSeriesNavigationResponse(BaseModel):
    """Navigation across sibling chains in the same variant/property/test series."""

    series_key: str = Field(..., description="series key")
    varying_axis: EvidenceChainVaryingAxisResponse = Field(..., description="变化轴")
    siblings: list[ResultSeriesSiblingResponse] = Field(
        default_factory=list,
        description="同 series 的 result siblings",
    )
