from __future__ import annotations

from pydantic import BaseModel, Field

from controllers.schemas.core.comparisons import ComparabilityStatus


class ResultListItemResponse(BaseModel):
    """Collection-facing product result summary."""

    result_id: str = Field(..., description="结果 ID")
    document_id: str = Field(..., description="来源文档 ID")
    document_title: str | None = Field(default=None, description="来源文档标题")
    material_label: str = Field(..., description="材料标签")
    variant_label: str | None = Field(default=None, description="样品标签")
    property: str = Field(..., description="性质指标")
    value: float | None = Field(default=None, description="结果数值")
    unit: str | None = Field(default=None, description="结果单位")
    summary: str = Field(..., description="结果摘要")
    baseline: str | None = Field(default=None, description="baseline")
    test_condition: str | None = Field(default=None, description="测试条件")
    process: str | None = Field(default=None, description="工艺")
    traceability_status: str = Field(..., description="可追溯性状态")
    comparability_status: ComparabilityStatus = Field(..., description="可比性状态")
    requires_expert_review: bool = Field(default=False, description="是否需要专家复核")


class ResultDocumentResponse(BaseModel):
    """Source document summary for one result."""

    document_id: str = Field(..., description="来源文档 ID")
    title: str | None = Field(default=None, description="文档标题")
    source_filename: str | None = Field(default=None, description="源文件名")


class ResultMaterialResponse(BaseModel):
    """Material context for one result."""

    label: str = Field(..., description="材料标签")
    variant_id: str | None = Field(default=None, description="样品变体 ID")
    variant_label: str | None = Field(default=None, description="样品标签")


class ResultMeasurementResponse(BaseModel):
    """Measurement payload for one result."""

    property: str = Field(..., description="性质指标")
    value: float | None = Field(default=None, description="结果数值")
    unit: str | None = Field(default=None, description="结果单位")
    result_type: str = Field(..., description="结果类型")
    summary: str = Field(..., description="结果摘要")
    statistic_type: str | None = Field(default=None, description="统计值类型")
    uncertainty: str | None = Field(default=None, description="不确定性说明")


class ResultContextResponse(BaseModel):
    """Context payload for one result."""

    process: str | None = Field(default=None, description="工艺")
    baseline: str | None = Field(default=None, description="标准化 baseline")
    baseline_reference: str | None = Field(default=None, description="原始 baseline 引用")
    test_condition: str | None = Field(default=None, description="测试条件")
    axis_name: str | None = Field(default=None, description="比较轴名称")
    axis_value: str | float | int | None = Field(default=None, description="比较轴值")
    axis_unit: str | None = Field(default=None, description="比较轴单位")


class ResultAssessmentResponse(BaseModel):
    """Collection-scoped assessment over one result."""

    comparability_status: ComparabilityStatus = Field(..., description="可比性状态")
    warnings: list[str] = Field(default_factory=list, description="警告")
    basis: list[str] = Field(default_factory=list, description="判断依据")
    missing_context: list[str] = Field(default_factory=list, description="缺失上下文")
    requires_expert_review: bool = Field(default=False, description="是否需要专家复核")
    assessment_epistemic_status: str = Field(..., description="评估认识论状态")


class ResultEvidenceItemResponse(BaseModel):
    """Evidence support item for one result."""

    evidence_id: str = Field(..., description="证据 ID")
    traceability_status: str = Field(..., description="可追溯性状态")
    source_type: str | None = Field(default=None, description="结果来源类型")
    anchor_ids: list[str] = Field(default_factory=list, description="关联 anchor IDs")


class ResultActionsResponse(BaseModel):
    """Drilldown actions for one result."""

    open_document: str | None = Field(default=None, description="打开文档详情")
    open_comparisons: str | None = Field(default=None, description="打开比较视图")
    open_evidence: str | None = Field(default=None, description="打开证据视图")


class ResultItemResponse(BaseModel):
    """Collection-facing product result detail."""

    result_id: str = Field(..., description="结果 ID")
    document: ResultDocumentResponse = Field(..., description="来源文档")
    material: ResultMaterialResponse = Field(..., description="材料信息")
    measurement: ResultMeasurementResponse = Field(..., description="测量值")
    context: ResultContextResponse = Field(..., description="上下文")
    assessment: ResultAssessmentResponse = Field(..., description="collection 判断")
    evidence: list[ResultEvidenceItemResponse] = Field(default_factory=list, description="证据列表")
    actions: ResultActionsResponse = Field(..., description="drilldown 动作")


class ResultListResponse(BaseModel):
    """Collection-facing result list."""

    collection_id: str = Field(..., description="集合 ID")
    total: int = Field(..., description="总条数")
    count: int = Field(..., description="返回条数")
    items: list[ResultListItemResponse] = Field(default_factory=list, description="结果列表")
