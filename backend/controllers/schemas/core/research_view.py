from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ResearchViewState = Literal["empty", "processing", "partial", "ready", "failed"]
ResearchViewSeverity = Literal["info", "warning", "error"]
EvidenceBackedValueStatus = Literal[
    "observed",
    "normalized",
    "inferred",
    "missing",
    "conflicted",
]
ConflictStatus = Literal["none", "duplicate_only", "conflicted"]
MatrixColumnRole = Literal["sample", "process", "property", "condition"]
ComparableGroupStatus = Literal["comparable", "limited", "blocked"]


class ResearchViewWarningResponse(BaseModel):
    """Structured warning attached to a research-view aggregate."""

    warning_id: str = Field(..., description="稳定 warning ID")
    severity: ResearchViewSeverity = Field(..., description="warning 级别")
    scope: str = Field(..., description="warning 作用域")
    code: str = Field(..., description="稳定 warning code")
    message: str = Field(..., description="用户可读说明")
    related_object_ids: list[str] = Field(
        default_factory=list,
        description="相关 fact、sample、document 或 group ID",
    )


class EvidenceReferenceResponse(BaseModel):
    """Traceable reference from an aggregate value back to extracted evidence."""

    evidence_ref_id: str = Field(..., description="证据引用 ID")
    fact_ids: list[str] = Field(default_factory=list, description="相关 fact IDs")
    anchor_ids: list[str] = Field(default_factory=list, description="相关 evidence anchor IDs")
    source_kind: str = Field(..., description="证据来源类型")
    document_id: str | None = Field(default=None, description="来源文档 ID")
    locator: dict[str, Any] = Field(default_factory=dict, description="页码、段落、表格或文本定位")
    confidence: float | None = Field(default=None, description="定位或抽取置信度")
    traceability_status: str = Field(..., description="证据可追溯状态")


class EvidenceBackedValueResponse(BaseModel):
    """Common evidence-backed value cell used by matrices and series."""

    display_value: str | None = Field(default=None, description="展示值")
    value: float | int | str | None = Field(default=None, description="原始或数值值")
    unit: str | None = Field(default=None, description="原始单位")
    normalized_value: float | int | str | None = Field(default=None, description="标准化值")
    normalized_unit: str | None = Field(default=None, description="标准化单位")
    status: EvidenceBackedValueStatus = Field(..., description="值状态")
    confidence: float | None = Field(default=None, description="值置信度")
    evidence_refs: list[EvidenceReferenceResponse] = Field(
        default_factory=list,
        description="支撑证据",
    )
    duplicate_count: int = Field(default=0, description="被折叠的重复 fact 数量")
    conflict_status: ConflictStatus = Field(default="none", description="冲突状态")
    warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="值级 warning",
    )
    label: str | None = Field(default=None, description="矩阵单元展示列名")


class SampleMatrixColumnResponse(BaseModel):
    """Column metadata for sample and cross-paper matrices."""

    column_id: str = Field(..., description="列 ID")
    label: str = Field(..., description="展示列名")
    role: MatrixColumnRole = Field(..., description="列角色")
    value_key: str = Field(..., description="row 内取值 key")


class SampleMatrixRowResponse(BaseModel):
    """One paper-level sample or variant row."""

    row_id: str = Field(..., description="矩阵行 ID")
    sample_id: str = Field(..., description="样品或 variant ID")
    sample_label: str | None = Field(default=None, description="样品展示名")
    material: str | None = Field(default=None, description="材料体系")
    process_context: dict[str, Any] = Field(default_factory=dict, description="工艺上下文")
    variable_axis: str | None = Field(default=None, description="变量轴")
    variable_value: Any = Field(default=None, description="变量取值")
    values: dict[str, EvidenceBackedValueResponse] = Field(
        default_factory=dict,
        description="按 property/condition key 组织的性能值",
    )
    evidence_refs: list[EvidenceReferenceResponse] = Field(
        default_factory=list,
        description="样品行证据",
    )
    warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="行级 warning",
    )


class SampleMatrixResponse(BaseModel):
    """Paper-level sample matrix."""

    matrix_id: str = Field(..., description="矩阵 ID")
    document_id: str = Field(..., description="文档 ID")
    state: ResearchViewState = Field(..., description="矩阵状态")
    columns: list[SampleMatrixColumnResponse] = Field(default_factory=list, description="列")
    rows: list[SampleMatrixRowResponse] = Field(default_factory=list, description="行")
    warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="矩阵 warning",
    )


class ConditionSeriesPointResponse(BaseModel):
    """One point in a condition series."""

    point_id: str = Field(..., description="series point ID")
    condition_value: float | int | str | None = Field(default=None, description="条件取值")
    condition_unit: str | None = Field(default=None, description="条件单位")
    result: EvidenceBackedValueResponse = Field(..., description="该条件下的结果")
    evidence_refs: list[EvidenceReferenceResponse] = Field(
        default_factory=list,
        description="点级证据",
    )
    warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="点级 warning",
    )


class ConditionSeriesResponse(BaseModel):
    """Values for one sample/property across a condition axis."""

    series_id: str = Field(..., description="series ID")
    document_id: str = Field(..., description="文档 ID")
    sample_id: str = Field(..., description="样品 ID")
    sample_label: str | None = Field(default=None, description="样品展示名")
    property: str = Field(..., description="性能指标")
    condition_axis: dict[str, Any] = Field(default_factory=dict, description="条件轴")
    points: list[ConditionSeriesPointResponse] = Field(default_factory=list, description="点")
    warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="series warning",
    )


class PaperAggregationOverviewResponse(BaseModel):
    """Paper-level research overview."""

    document_id: str = Field(..., description="文档 ID")
    material_systems: list[str] = Field(default_factory=list, description="材料体系")
    sample_variant_count: int = Field(default=0, description="样品/variant 数")
    main_process_variables: list[str] = Field(default_factory=list, description="主要工艺变量")
    measured_properties: list[str] = Field(default_factory=list, description="性能指标")
    condition_families: list[str] = Field(default_factory=list, description="测试条件族")
    warning_count: int = Field(default=0, description="warning 数")


class PaperAggregationResponse(BaseModel):
    """Paper-level research aggregation response."""

    collection_id: str = Field(..., description="集合 ID")
    document_id: str = Field(..., description="文档 ID")
    paper_title: str | None = Field(default=None, description="论文标题")
    state: ResearchViewState = Field(..., description="聚合状态")
    overview: PaperAggregationOverviewResponse = Field(..., description="论文概览")
    sample_matrix: SampleMatrixResponse = Field(..., description="样品矩阵")
    condition_series: list[ConditionSeriesResponse] = Field(
        default_factory=list,
        description="条件序列",
    )
    evidence_links: dict[str, str | None] = Field(default_factory=dict, description="证据链接")
    debug_links: dict[str, str | None] = Field(default_factory=dict, description="调试链接")
    warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="聚合 warning",
    )


class PaperCoverageRowResponse(BaseModel):
    """Collection-level paper coverage row."""

    document_id: str = Field(..., description="文档 ID")
    title: str | None = Field(default=None, description="标题")
    state: ResearchViewState = Field(..., description="文档聚合状态")
    sample_count: int = Field(default=0, description="样品数")
    process_param_count: int = Field(default=0, description="工艺参数数")
    measurement_count: int = Field(default=0, description="measurement result 数")
    condition_count: int = Field(default=0, description="测试条件数")
    evidence_count: int = Field(default=0, description="evidence anchor 数")
    issue_count: int = Field(default=0, description="结构化问题数")
    primary_warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="主要 warning",
    )
    links: dict[str, str | None] = Field(default_factory=dict, description="跳转链接")


class CrossPaperMatrixRowResponse(BaseModel):
    """One row in a collection-level comparison matrix."""

    row_id: str = Field(..., description="矩阵行 ID")
    document_id: str = Field(..., description="文档 ID")
    sample_id: str | None = Field(default=None, description="样品 ID")
    sample_label: str | None = Field(default=None, description="样品展示名")
    material: str | None = Field(default=None, description="材料体系")
    process_context: dict[str, Any] = Field(default_factory=dict, description="工艺上下文")
    variable_value: Any = Field(default=None, description="变量取值")
    test_condition: str | None = Field(default=None, description="测试条件")
    property: str = Field(..., description="性能指标")
    result: EvidenceBackedValueResponse = Field(..., description="结果值")
    evidence_refs: list[EvidenceReferenceResponse] = Field(
        default_factory=list,
        description="支撑证据",
    )
    warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="行级 warning",
    )


class CrossPaperMatrixResponse(BaseModel):
    """Collection-level matrix for one comparable group."""

    matrix_id: str = Field(..., description="矩阵 ID")
    group_id: str = Field(..., description="comparable group ID")
    columns: list[SampleMatrixColumnResponse] = Field(default_factory=list, description="列")
    rows: list[CrossPaperMatrixRowResponse] = Field(default_factory=list, description="行")
    warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="矩阵 warning",
    )


class ComparableGroupResponse(BaseModel):
    """Primary collection-level comparison object."""

    group_id: str = Field(..., description="group ID")
    title: str = Field(..., description="展示标题")
    material_system: str = Field(..., description="材料体系")
    process_family: str = Field(..., description="工艺族或标准化工艺")
    variable_axis: str = Field(..., description="变量轴")
    fixed_conditions: dict[str, Any] = Field(default_factory=dict, description="固定条件")
    properties: list[str] = Field(default_factory=list, description="性能指标")
    documents: list[str] = Field(default_factory=list, description="覆盖文档")
    samples: list[str] = Field(default_factory=list, description="覆盖样品")
    comparability_status: ComparableGroupStatus = Field(..., description="可比性状态")
    matrix: CrossPaperMatrixResponse = Field(..., description="组内矩阵")
    evidence_refs: list[EvidenceReferenceResponse] = Field(
        default_factory=list,
        description="组级证据",
    )
    warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="组级 warning",
    )


class CollectionAggregationOverviewResponse(BaseModel):
    """Collection-level research overview."""

    collection_id: str = Field(..., description="集合 ID")
    document_count: int = Field(default=0, description="文档数")
    sample_variant_count: int = Field(default=0, description="样品/variant 数")
    measurement_count: int = Field(default=0, description="measurement result 数")
    condition_count: int = Field(default=0, description="测试条件数")
    evidence_count: int = Field(default=0, description="evidence anchor 数")
    comparable_group_count: int = Field(default=0, description="可比 group 数")
    material_systems: list[str] = Field(default_factory=list, description="材料体系")
    process_variables: list[str] = Field(default_factory=list, description="工艺变量")
    measured_properties: list[str] = Field(default_factory=list, description="性能指标")
    condition_families: list[str] = Field(default_factory=list, description="条件族")


class CollectionAggregationResponse(BaseModel):
    """Collection-level research aggregation response."""

    collection_id: str = Field(..., description="集合 ID")
    state: ResearchViewState = Field(..., description="聚合状态")
    overview: CollectionAggregationOverviewResponse = Field(..., description="集合概览")
    paper_coverage: list[PaperCoverageRowResponse] = Field(
        default_factory=list,
        description="文档覆盖",
    )
    comparable_groups: list[ComparableGroupResponse] = Field(
        default_factory=list,
        description="比较组",
    )
    cross_paper_matrices: list[CrossPaperMatrixResponse] = Field(
        default_factory=list,
        description="跨论文矩阵",
    )
    trend_series: list[ConditionSeriesResponse] = Field(
        default_factory=list,
        description="跨论文趋势序列",
    )
    evidence_links: dict[str, str | None] = Field(default_factory=dict, description="证据链接")
    debug_links: dict[str, str | None] = Field(default_factory=dict, description="调试链接")
    warnings: list[ResearchViewWarningResponse] = Field(
        default_factory=list,
        description="聚合 warning",
    )
