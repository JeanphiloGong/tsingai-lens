from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..source.collection import CollectionResponse
from ..source.task import TaskResponse


WorkflowStageStatus = Literal[
    "not_started",
    "processing",
    "ready",
    "limited",
    "not_applicable",
    "failed",
]


class WorkspaceArtifactStatusResponse(BaseModel):
    """Collection-scoped artifact readiness summary."""

    output_path: str = Field(..., description="集合输出目录")
    documents_generated: bool = Field(default=False, description="documents.parquet 是否存在")
    documents_ready: bool = Field(default=False, description="documents.parquet 是否存在且非空")
    document_profiles_generated: bool = Field(default=False, description="document_profiles.parquet 是否存在")
    document_profiles_ready: bool = Field(default=False, description="document_profiles.parquet 是否存在且非空")
    evidence_anchors_generated: bool = Field(default=False, description="evidence_anchors.parquet 是否存在")
    evidence_anchors_ready: bool = Field(default=False, description="evidence_anchors.parquet 是否存在且非空")
    method_facts_generated: bool = Field(default=False, description="method_facts.parquet 是否存在")
    method_facts_ready: bool = Field(default=False, description="method_facts.parquet 是否存在且非空")
    evidence_cards_generated: bool = Field(default=False, description="evidence_cards.parquet 是否存在")
    evidence_cards_ready: bool = Field(default=False, description="evidence_cards.parquet 是否存在且非空")
    characterization_observations_generated: bool = Field(default=False, description="characterization_observations.parquet 是否存在")
    characterization_observations_ready: bool = Field(default=False, description="characterization_observations.parquet 是否存在且非空")
    structure_features_generated: bool = Field(default=False, description="structure_features.parquet 是否存在")
    structure_features_ready: bool = Field(default=False, description="structure_features.parquet 是否存在且非空")
    test_conditions_generated: bool = Field(default=False, description="test_conditions.parquet 是否存在")
    test_conditions_ready: bool = Field(default=False, description="test_conditions.parquet 是否存在且非空")
    baseline_references_generated: bool = Field(default=False, description="baseline_references.parquet 是否存在")
    baseline_references_ready: bool = Field(default=False, description="baseline_references.parquet 是否存在且非空")
    sample_variants_generated: bool = Field(default=False, description="sample_variants.parquet 是否存在")
    sample_variants_ready: bool = Field(default=False, description="sample_variants.parquet 是否存在且非空")
    measurement_results_generated: bool = Field(default=False, description="measurement_results.parquet 是否存在")
    measurement_results_ready: bool = Field(default=False, description="measurement_results.parquet 是否存在且非空")
    comparison_rows_generated: bool = Field(default=False, description="comparison_rows.parquet 是否存在")
    comparison_rows_ready: bool = Field(default=False, description="comparison_rows.parquet 是否存在且非空")
    graph_generated: bool = Field(default=False, description="Core graph 投影输入是否已生成")
    graph_ready: bool = Field(default=False, description="Core graph 视图是否可用")
    blocks_generated: bool = Field(default=False, description="blocks.parquet 是否存在")
    blocks_ready: bool = Field(default=False, description="blocks.parquet 是否存在且非空")
    table_rows_generated: bool = Field(default=False, description="table_rows.parquet 是否存在")
    table_rows_ready: bool = Field(default=False, description="table_rows.parquet 是否存在且非空")
    table_cells_generated: bool = Field(default=False, description="table_cells.parquet 是否存在")
    table_cells_ready: bool = Field(default=False, description="table_cells.parquet 是否存在且非空")
    procedure_blocks_generated: bool = Field(default=False, description="procedure_blocks.parquet 是否存在")
    procedure_blocks_ready: bool = Field(
        default=False,
        description="procedure_blocks.parquet 是否存在且非空",
    )
    protocol_steps_generated: bool = Field(default=False, description="protocol_steps.parquet 是否存在")
    protocol_steps_ready: bool = Field(
        default=False,
        description="protocol_steps.parquet 是否存在且非空",
    )
    updated_at: str = Field(..., description="更新时间")


class WorkspaceCapabilitiesResponse(BaseModel):
    """Feature gates exposed to the frontend workspace."""

    can_view_graph: bool = Field(default=False, description="是否可查看图谱")
    can_download_graphml: bool = Field(default=False, description="是否可导出 GraphML")
    can_view_protocol_steps: bool = Field(default=False, description="是否可查看 protocol steps")
    can_search_protocol: bool = Field(default=False, description="是否可检索 protocol steps")
    can_generate_sop: bool = Field(default=False, description="是否可生成 SOP 草案")


class WorkspaceStageResponse(BaseModel):
    """Single workflow stage status."""

    status: WorkflowStageStatus = Field(..., description="workflow 阶段状态")
    detail: str | None = Field(default=None, description="状态说明")


class WorkspaceWorkflowResponse(BaseModel):
    """Primary workflow readiness model for Lens v1."""

    documents: WorkspaceStageResponse = Field(..., description="documents 阶段")
    evidence: WorkspaceStageResponse = Field(..., description="evidence 阶段")
    comparisons: WorkspaceStageResponse = Field(..., description="comparisons 阶段")
    protocol: WorkspaceStageResponse = Field(..., description="protocol 阶段")


class WorkspaceDocumentSummaryResponse(BaseModel):
    """Collection-level document rollup."""

    total_documents: int = Field(default=0, description="文档总数")
    by_doc_type: dict[str, int] = Field(default_factory=dict, description="按文档类型统计")
    by_protocol_extractable: dict[str, int] = Field(
        default_factory=dict,
        description="按 protocol suitability 统计",
    )


class WorkspaceWarningResponse(BaseModel):
    """Collection-facing warning for the workspace."""

    code: str = Field(..., description="稳定 warning code")
    severity: Literal["info", "warning", "error"] = Field(..., description="警告级别")
    message: str = Field(..., description="警告说明")


class WorkspaceLinksResponse(BaseModel):
    """Primary navigation links for the frontend workspace."""

    documents_profiles: str | None = Field(default=None, description="documents/profiles 路径")
    evidence_cards: str | None = Field(default=None, description="evidence/cards 路径")
    comparisons: str | None = Field(default=None, description="comparisons 路径")
    protocol_steps: str | None = Field(default=None, description="protocol/steps 路径")


class WorkspaceOverviewResponse(BaseModel):
    """Top-level collection workspace payload."""

    collection: CollectionResponse = Field(..., description="集合元数据")
    file_count: int = Field(default=0, description="集合文件数")
    status_summary: str = Field(..., description="工作区摘要状态")
    artifacts: WorkspaceArtifactStatusResponse = Field(..., description="产物状态")
    workflow: WorkspaceWorkflowResponse | None = Field(default=None, description="主 workflow 状态")
    document_summary: WorkspaceDocumentSummaryResponse = Field(
        default_factory=WorkspaceDocumentSummaryResponse,
        description="document profile 汇总",
    )
    warnings: list[WorkspaceWarningResponse] = Field(default_factory=list, description="集合级风险提示")
    latest_task: TaskResponse | None = Field(default=None, description="最近一次任务")
    recent_tasks: list[TaskResponse] = Field(default_factory=list, description="最近任务列表")
    capabilities: WorkspaceCapabilitiesResponse = Field(..., description="工作区能力开关")
    links: WorkspaceLinksResponse = Field(default_factory=WorkspaceLinksResponse, description="主资源跳转")
