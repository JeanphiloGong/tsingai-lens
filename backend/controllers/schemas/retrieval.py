# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

from typing import Any, Literal

from pydantic import BaseModel, Field

from retrieval.config.enums import IndexingMethod, SearchMethod


class IndexRequest(BaseModel):
    """Request payload to start indexing."""

    collection_id: str | None = Field(default=None, description="集合 ID")
    method: IndexingMethod | str = Field(
        default=IndexingMethod.Standard, description="索引模式"
    )
    is_update_run: bool = Field(default=False, description="是否执行增量更新")
    verbose: bool = Field(default=False, description="是否输出详细日志")
    additional_context: dict | None = Field(
        default=None, description="透传到 pipeline state 的附加上下文"
    )


class IndexResponse(BaseModel):
    """Response payload summarizing pipeline execution."""

    status: str
    workflows: list[str]
    errors: list[str] | None = None
    output_path: str | None = None
    stored_input_path: str | None = None


class QueryRequest(BaseModel):
    """Request payload to query an indexed knowledge graph."""

    query: str = Field(..., description="检索问题")
    method: SearchMethod | str = Field(
        default=SearchMethod.GLOBAL, description="检索方法"
    )
    collection_id: str | None = Field(default=None, description="集合 ID")
    response_type: str = Field(
        default="List of 5-7 Points", description="回答格式描述"
    )
    community_level: int | None = Field(
        default=2, description="社区层级（local/drift/global 可用）"
    )
    dynamic_community_selection: bool = Field(
        default=False, description="global 模式动态社区选择"
    )
    include_context: bool = Field(
        default=False, description="是否返回 context_data"
    )
    verbose: bool = Field(default=False, description="是否输出详细日志")


class QueryResponse(BaseModel):
    """Response payload for query results."""

    answer: object
    method: str
    collection_id: str
    output_path: str
    context_data: dict | list | None = None


class InputUploadItem(BaseModel):
    """Uploaded input file metadata."""

    original_filename: str
    stored_name: str
    stored_path: str
    converted_to_text: bool = False
    size_bytes: int


class InputUploadResponse(BaseModel):
    """Response for input file uploads without indexing."""

    count: int
    items: list[InputUploadItem]


class CollectionFileRecord(BaseModel):
    """Metadata for a collection input file."""

    key: str
    original_filename: str | None = None
    stored_path: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None


class CollectionFileListResponse(BaseModel):
    """Response containing collection input files."""

    collection_id: str
    count: int
    items: list[CollectionFileRecord]


class CollectionFileDeleteResponse(BaseModel):
    """Response payload for collection file deletion."""

    collection_id: str
    key: str
    deleted_at: str | None = None
    status: str = "deleted"


class ReportCommunitySummary(BaseModel):
    """Summary for a community report."""

    report_id: str | None = None
    community_id: int | None = None
    human_readable_id: int | None = None
    level: int | None = None
    parent: int | None = None
    children: list[int] | None = None
    title: str | None = None
    summary: str | None = None
    findings: Any | None = None
    rating: float | None = None
    size: int | None = None


class ReportCommunityListResponse(BaseModel):
    """Response containing community report summaries."""

    collection_id: str
    level: int | None = None
    total: int
    count: int
    items: list[ReportCommunitySummary]


class ReportEntityItem(BaseModel):
    """Entity item for community report details."""

    id: str
    title: str
    type: str | None = None
    description: str | None = None
    degree: int | None = None
    frequency: int | None = None


class ReportRelationshipItem(BaseModel):
    """Relationship item for community report details."""

    id: str
    source: str
    target: str
    description: str | None = None
    weight: float | None = None
    combined_degree: float | None = None
    text_unit_count: int | None = None


class ReportDocumentItem(BaseModel):
    """Document item for community report details."""

    id: str
    title: str | None = None
    creation_date: str | None = None


class ReportCommunityDetailResponse(BaseModel):
    """Community report detail response."""

    collection_id: str
    community_id: int | None = None
    human_readable_id: int | None = None
    level: int | None = None
    parent: int | None = None
    children: list[int] | None = None
    title: str | None = None
    summary: str | None = None
    findings: Any | None = None
    rating: float | None = None
    size: int | None = None
    document_count: int | None = None
    text_unit_count: int | None = None
    entities: list[ReportEntityItem]
    relationships: list[ReportRelationshipItem]
    documents: list[ReportDocumentItem]


class ReportPatternItem(BaseModel):
    """Pattern summary item."""

    community_id: int | None = None
    title: str | None = None
    summary: str | None = None
    findings: Any | None = None
    rating: float | None = None
    size: int | None = None
    level: int | None = None


class ReportPatternsResponse(BaseModel):
    """Response for pattern summaries."""

    collection_id: str
    level: int | None = None
    total_communities: int
    total_entities: int | None = None
    total_relationships: int | None = None
    total_documents: int | None = None
    count: int
    items: list[ReportPatternItem]


class CollectionCreateRequest(BaseModel):
    """Request payload to create a collection."""

    name: str | None = Field(default=None, description="集合名称")


class CollectionRecord(BaseModel):
    """Collection metadata."""

    id: str
    name: str | None = None
    created_at: str
    updated_at: str | None = None
    status: str | None = None
    document_count: int | None = None
    entity_count: int | None = None


class CollectionListResponse(BaseModel):
    """Response containing available collections."""

    items: list[CollectionRecord]


class CollectionDeleteResponse(BaseModel):
    """Response payload for collection deletion."""

    id: str
    deleted_at: str
    status: str = "deleted"


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
        default=None, description="GraphRAG 输出目录；为空时走默认配置"
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
        default=None, description="GraphRAG 输出目录；为空时走默认配置"
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
