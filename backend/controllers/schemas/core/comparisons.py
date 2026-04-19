from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ComparabilityStatus = Literal["comparable", "limited", "not_comparable", "insufficient"]


class ComparisonDisplayResponse(BaseModel):
    """User-facing comparison row display fields."""

    material_system_normalized: str = Field(..., description="标准化材料体系")
    process_normalized: str = Field(..., description="标准化工艺")
    variant_id: str | None = Field(default=None, description="样品变体 ID")
    variant_label: str | None = Field(default=None, description="样品变体标签")
    variable_axis: str | None = Field(default=None, description="变量轴名称")
    variable_value: str | float | int | None = Field(default=None, description="变量轴取值")
    property_normalized: str = Field(..., description="标准化性质指标")
    result_type: str = Field(..., description="结果类型")
    result_summary: str = Field(..., description="结果摘要")
    value: float | None = Field(default=None, description="可直接展示的数值")
    unit: str | None = Field(default=None, description="单位")
    test_condition_normalized: str = Field(..., description="标准化测试条件")
    baseline_reference: str | None = Field(default=None, description="baseline 参考对象")
    baseline_normalized: str = Field(..., description="标准化 baseline")


class ComparisonEvidenceBundleResponse(BaseModel):
    """Evidence bundle that supports one comparison row."""

    result_source_type: str | None = Field(default=None, description="结果来源类型")
    supporting_evidence_ids: list[str] = Field(default_factory=list, description="支撑 evidence IDs")
    supporting_anchor_ids: list[str] = Field(default_factory=list, description="支撑 anchor IDs")
    characterization_observation_ids: list[str] = Field(
        default_factory=list,
        description="关联 characterization observation IDs",
    )
    structure_feature_ids: list[str] = Field(
        default_factory=list,
        description="关联 structure feature IDs",
    )


class ComparisonAssessmentResponse(BaseModel):
    """System assessment over the comparison row."""

    comparability_status: ComparabilityStatus = Field(..., description="可比性状态")
    comparability_warnings: list[str] = Field(default_factory=list, description="可比性警告")
    comparability_basis: list[str] = Field(default_factory=list, description="可比性判断依据")
    requires_expert_review: bool = Field(default=False, description="是否需要专家复核")
    assessment_epistemic_status: str = Field(..., description="判断的认识论状态")


class ComparisonUncertaintyResponse(BaseModel):
    """Missing or unresolved context around one row."""

    missing_critical_context: list[str] = Field(default_factory=list, description="缺失的关键上下文")
    unresolved_fields: list[str] = Field(default_factory=list, description="未解析字段")
    unresolved_baseline_link: bool = Field(default=False, description="baseline 链接是否未解析")
    unresolved_condition_link: bool = Field(default=False, description="condition 链接是否未解析")


class ComparisonRowItemResponse(BaseModel):
    """Single collection-facing comparison row."""

    row_id: str = Field(..., description="comparison row ID")
    collection_id: str = Field(..., description="集合 ID")
    source_document_id: str = Field(..., description="来源文档 ID")
    display: ComparisonDisplayResponse = Field(..., description="展示字段")
    evidence_bundle: ComparisonEvidenceBundleResponse = Field(..., description="证据包")
    assessment: ComparisonAssessmentResponse = Field(..., description="系统判断")
    uncertainty: ComparisonUncertaintyResponse = Field(..., description="不确定性与缺失上下文")


class ComparisonRowListResponse(BaseModel):
    """Collection-scoped comparison row listing."""

    collection_id: str = Field(..., description="集合 ID")
    total: int = Field(..., description="总条数")
    count: int = Field(..., description="返回条数")
    items: list[ComparisonRowItemResponse] = Field(default_factory=list, description="comparison row 列表")
