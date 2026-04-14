from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class NormalizedValueItem(BaseModel):
    """Normalized numeric value with raw text traceability."""

    value: float | None = Field(default=None, description="归一化后的数值")
    unit: str | None = Field(default=None, description="归一化单位，如 K、s、MPa")
    raw_value: str | None = Field(default=None, description="原始文本值")
    operator: str | None = Field(
        default=None, description="比较符，如 =、>、<、~、range"
    )
    min_value: float | None = Field(default=None, description="区间下界")
    max_value: float | None = Field(default=None, description="区间上界")
    status: Literal["reported", "inferred", "not_reported", "ambiguous"] = Field(
        default="not_reported", description="值状态"
    )


class ConditionItem(BaseModel):
    """Normalized experimental conditions for a protocol step."""

    temperature: NormalizedValueItem | None = Field(
        default=None, description="温度，统一建议为 K"
    )
    duration: NormalizedValueItem | None = Field(
        default=None, description="时长，统一建议为 s"
    )
    pressure: NormalizedValueItem | None = Field(
        default=None, description="压力，统一建议为 Pa"
    )
    heating_rate: NormalizedValueItem | None = Field(
        default=None, description="升温速率"
    )
    cooling_rate: NormalizedValueItem | None = Field(
        default=None, description="降温速率"
    )
    ph: NormalizedValueItem | None = Field(default=None, description="pH")
    atmosphere: str | None = Field(default=None, description="气氛，如 Ar、Air")
    environment: str | None = Field(default=None, description="环境补充说明")
    raw_text: str | None = Field(default=None, description="原始条件片段")


class MaterialRefItem(BaseModel):
    """Material or reagent reference used in a protocol step."""

    name: str = Field(..., description="材料或试剂名称")
    formula: str | None = Field(default=None, description="化学式")
    role: Literal[
        "precursor",
        "solvent",
        "additive",
        "matrix",
        "filler",
        "sample",
        "product",
        "other",
    ] = Field(default="other", description="材料角色")
    amount: NormalizedValueItem | None = Field(default=None, description="用量")
    composition_note: str | None = Field(default=None, description="配比或组成备注")
    grade: str | None = Field(default=None, description="牌号/等级")
    source_text: str | None = Field(default=None, description="原始片段")


class MeasurementSpecItem(BaseModel):
    """Measurement or characterization plan."""

    method: str = Field(..., description="表征或测试方法")
    instrument: str | None = Field(default=None, description="设备名称")
    target_property: str | None = Field(default=None, description="目标性质")
    metrics: list[str] = Field(default_factory=list, description="指标字段")
    conditions: dict[str, Any] = Field(
        default_factory=dict, description="测试条件补充"
    )
    output_ref: str | None = Field(default=None, description="输出或图表引用")
    source_text: str | None = Field(default=None, description="原始片段")


class ControlSpecItem(BaseModel):
    """Control or baseline definition."""

    control_type: Literal[
        "baseline",
        "blank",
        "untreated",
        "literature",
        "ablation",
        "other",
    ] = Field(default="other", description="对照类型")
    description: str = Field(..., description="对照描述")
    rationale: str | None = Field(default=None, description="对照理由")
    source_text: str | None = Field(default=None, description="原始片段")


class EvidenceRefItem(BaseModel):
    """Evidence anchor back to source paper text."""

    paper_id: str = Field(..., description="论文 ID")
    section_id: str | None = Field(default=None, description="section ID")
    block_id: str | None = Field(default=None, description="procedure block ID")
    snippet_id: str | None = Field(default=None, description="文本片段 ID")
    section_type: str | None = Field(default=None, description="section 类型")
    page_start: int | None = Field(default=None, description="起始页")
    page_end: int | None = Field(default=None, description="结束页")
    figure_or_table: str | None = Field(default=None, description="图表引用")
    quote_span: str | None = Field(default=None, description="原文摘录")
    source_text: str | None = Field(default=None, description="证据全文片段")
    confidence_score: float | None = Field(default=None, description="证据置信度")


class ProtocolStepItem(BaseModel):
    """Structured protocol step item."""

    step_id: str = Field(..., description="步骤 ID")
    paper_id: str = Field(..., description="来源论文 ID")
    paper_title: str | None = Field(default=None, description="来源论文标题")
    order: int = Field(..., description="步骤顺序")
    action: str = Field(..., description="核心动作")
    section_id: str | None = Field(default=None, description="section ID")
    block_id: str | None = Field(default=None, description="block ID")
    phase: Literal[
        "preparation",
        "synthesis",
        "post_treatment",
        "characterization",
        "property_test",
        "analysis",
        "other",
    ] = Field(default="other", description="步骤阶段")
    materials: list[MaterialRefItem] = Field(
        default_factory=list, description="材料与试剂"
    )
    conditions: ConditionItem = Field(
        default_factory=ConditionItem, description="实验条件"
    )
    purpose: str | None = Field(default=None, description="步骤目的")
    expected_output: str | None = Field(default=None, description="期望输出")
    characterization: list[MeasurementSpecItem] = Field(
        default_factory=list, description="表征与测试"
    )
    controls: list[ControlSpecItem] = Field(
        default_factory=list, description="对照信息"
    )
    evidence_refs: list[EvidenceRefItem] = Field(
        default_factory=list, description="证据锚点"
    )
    confidence_score: float | None = Field(default=None, description="步骤置信度")


class SOPDraftItem(BaseModel):
    """Structured SOP draft composed from protocol steps."""

    sop_id: str = Field(..., description="SOP ID")
    objective: str = Field(..., description="实验目标")
    hypothesis: str | None = Field(default=None, description="实验假设")
    variables: list[str] = Field(default_factory=list, description="关键变量")
    constraints: dict[str, Any] = Field(
        default_factory=dict, description="设备/温度/时间等约束"
    )
    controls: list[ControlSpecItem] = Field(
        default_factory=list, description="对照设计"
    )
    steps: list[ProtocolStepItem] = Field(
        default_factory=list, description="结构化步骤"
    )
    measurement_plan: list[MeasurementSpecItem] = Field(
        default_factory=list, description="测量与表征计划"
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list, description="验收标准"
    )
    risks: list[str] = Field(default_factory=list, description="风险项")
    open_questions: list[str] = Field(default_factory=list, description="未决问题")
    review_status: Literal[
        "draft",
        "human_review_required",
        "approved",
        "changes_requested",
        "rejected",
    ] = Field(default="draft", description="审核状态")


class ProtocolExtractRequest(BaseModel):
    """Request payload to generate structured protocol artifacts."""

    output_path: str | None = Field(
        default=None, description="集合输出目录；为空时走默认配置"
    )
    paper_ids: list[str] = Field(
        default_factory=list, description="限定论文 ID 范围"
    )
    overwrite: bool = Field(default=False, description="是否覆盖已有协议产物")


class ProtocolArtifactCounts(BaseModel):
    """Counts for generated protocol artifacts."""

    sections: int = 0
    procedure_blocks: int = 0
    protocol_steps: int = 0


class ProtocolExtractResponse(BaseModel):
    """Response after protocol artifact extraction."""

    status: str = Field(..., description="执行状态")
    output_path: str = Field(..., description="协议产物目录")
    artifacts: list[str] = Field(default_factory=list, description="产物文件名")
    counts: ProtocolArtifactCounts = Field(
        default_factory=ProtocolArtifactCounts, description="产物计数"
    )
    warnings: list[str] = Field(default_factory=list, description="警告信息")


class ProtocolStepListResponse(BaseModel):
    """Response for listing extracted protocol steps."""

    output_path: str = Field(..., description="协议产物目录")
    count: int = Field(..., description="返回数量")
    items: list[ProtocolStepItem] = Field(default_factory=list, description="步骤列表")


class ProtocolSearchHit(BaseModel):
    """Single protocol search result."""

    step_id: str = Field(..., description="步骤 ID")
    paper_id: str = Field(..., description="来源论文 ID")
    paper_title: str | None = Field(default=None, description="来源论文标题")
    section_id: str | None = Field(default=None, description="section ID")
    block_id: str | None = Field(default=None, description="block ID")
    action: str = Field(..., description="命中动作")
    matched_fields: list[str] = Field(
        default_factory=list, description="命中的字段"
    )
    excerpt: str | None = Field(default=None, description="命中摘录")
    score: float | None = Field(default=None, description="匹配分数")


class ProtocolSearchResponse(BaseModel):
    """Response for protocol-level search."""

    query: str = Field(..., description="检索词")
    output_path: str = Field(..., description="协议产物目录")
    count: int = Field(..., description="返回数量")
    items: list[ProtocolSearchHit] = Field(default_factory=list, description="结果列表")


class SOPDraftRequest(BaseModel):
    """Request payload to generate an SOP draft."""

    output_path: str | None = Field(
        default=None, description="集合输出目录；为空时走默认配置"
    )
    goal: str = Field(..., description="实验目标")
    paper_ids: list[str] = Field(default_factory=list, description="限定论文 ID")
    step_ids: list[str] = Field(default_factory=list, description="限定步骤 ID")
    target_properties: list[str] = Field(
        default_factory=list, description="目标性质"
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict, description="实验约束"
    )
    max_steps: int | None = Field(default=None, description="最大步骤数")


class SOPDraftResponse(BaseModel):
    """Response containing a structured SOP draft."""

    output_path: str = Field(..., description="协议产物目录")
    sop_draft: SOPDraftItem = Field(..., description="结构化 SOP 草案")
    warnings: list[str] = Field(default_factory=list, description="警告信息")
