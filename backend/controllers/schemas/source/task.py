from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


TaskStatus = Literal["queued", "running", "completed", "partial_success", "failed"]
TaskStage = Literal[
    "queued",
    "files_registered",
    "source_artifacts_started",
    "source_artifacts_completed",
    "document_profiles_started",
    "document_profiles_completed",
    "objective_candidates_started",
    "objective_candidates_completed",
    "objective_paper_skim_started",
    "objective_discovery_started",
    "artifacts_ready",
    "failed",
]


class BuildTaskCreateRequest(BaseModel):
    """Request payload to start a collection build task."""

    model_config = ConfigDict(extra="ignore")

    verbose: bool = Field(default=False, description="是否输出详细日志")
    additional_context: dict[str, Any] | None = Field(
        default=None,
        description="透传到 pipeline state 的附加上下文",
    )


class TaskResponse(BaseModel):
    """Task metadata returned to clients."""

    task_id: str = Field(..., description="任务 ID")
    collection_id: str = Field(..., description="集合 ID")
    task_type: str = Field(..., description="任务类型")
    status: TaskStatus = Field(..., description="任务状态")
    current_stage: TaskStage = Field(..., description="当前阶段")
    progress_percent: int = Field(default=0, description="进度百分比")
    progress_detail: dict[str, Any] | None = Field(
        default=None,
        description="当前阶段的可读子进度，例如 current/total/unit/message",
    )
    output_path: str | None = Field(default=None, description="输出目录")
    errors: list[str] = Field(default_factory=list, description="错误列表")
    warnings: list[str] = Field(default_factory=list, description="警告列表")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="完成时间")


class ArtifactStatusResponse(BaseModel):
    """Artifact readiness payload for a task or collection."""

    task_id: str = Field(..., description="任务 ID")
    collection_id: str = Field(..., description="集合 ID")
    output_path: str = Field(..., description="输出目录")
    documents_generated: bool = Field(default=False, description="documents 是否已生成")
    documents_ready: bool = Field(default=False, description="documents 是否已生成且非空")
    document_profiles_generated: bool = Field(default=False, description="document_profiles 是否已生成")
    document_profiles_ready: bool = Field(default=False, description="document_profiles 是否已生成且非空")
    evidence_anchors_generated: bool = Field(default=False, description="evidence_anchors 是否已生成")
    evidence_anchors_ready: bool = Field(default=False, description="evidence_anchors 是否已生成且非空")
    method_facts_generated: bool = Field(default=False, description="method_facts 是否已生成")
    method_facts_ready: bool = Field(default=False, description="method_facts 是否已生成且非空")
    evidence_cards_generated: bool = Field(default=False, description="evidence_cards 是否已生成")
    evidence_cards_ready: bool = Field(default=False, description="evidence_cards 是否已生成且非空")
    characterization_observations_generated: bool = Field(default=False, description="characterization_observations 是否已生成")
    characterization_observations_ready: bool = Field(default=False, description="characterization_observations 是否已生成且非空")
    structure_features_generated: bool = Field(default=False, description="structure_features 是否已生成")
    structure_features_ready: bool = Field(default=False, description="structure_features 是否已生成且非空")
    test_conditions_generated: bool = Field(default=False, description="test_conditions 是否已生成")
    test_conditions_ready: bool = Field(default=False, description="test_conditions 是否已生成且非空")
    baseline_references_generated: bool = Field(default=False, description="baseline_references 是否已生成")
    baseline_references_ready: bool = Field(default=False, description="baseline_references 是否已生成且非空")
    sample_variants_generated: bool = Field(default=False, description="sample_variants 是否已生成")
    sample_variants_ready: bool = Field(default=False, description="sample_variants 是否已生成且非空")
    measurement_results_generated: bool = Field(default=False, description="measurement_results 是否已生成")
    measurement_results_ready: bool = Field(default=False, description="measurement_results 是否已生成且非空")
    comparable_results_generated: bool = Field(default=False, description="comparable_results 是否已生成")
    comparable_results_ready: bool = Field(default=False, description="comparable_results 是否已生成且非空")
    collection_comparable_results_generated: bool = Field(default=False, description="collection_comparable_results 是否已生成")
    collection_comparable_results_ready: bool = Field(default=False, description="collection_comparable_results 是否已生成且非空")
    collection_comparable_results_stale: bool = Field(
        default=False,
        description="collection_comparable_results 是否已因 policy/version drift 而过期",
    )
    comparison_rows_generated: bool = Field(default=False, description="comparison_rows 是否已生成")
    comparison_rows_ready: bool = Field(default=False, description="comparison_rows 是否已生成且非空")
    comparison_rows_stale: bool = Field(
        default=False,
        description="comparison_rows 是否因上游 scope artifact 过期而失效",
    )
    graph_generated: bool = Field(default=False, description="Core graph 所需 backbone 与 comparison semantic 输入是否均已生成")
    graph_ready: bool = Field(default=False, description="Core graph 视图是否可按需投影")
    graph_stale: bool = Field(
        default=False,
        description="Core graph 语义输入是否因 collection scope artifact 过期而不再 current",
    )
    blocks_generated: bool = Field(default=False, description="blocks 是否已生成")
    blocks_ready: bool = Field(default=False, description="blocks 是否已生成且非空")
    figures_generated: bool = Field(default=False, description="figures 是否已生成")
    figures_ready: bool = Field(default=False, description="figures 是否已生成且非空")
    table_rows_generated: bool = Field(default=False, description="table_rows 是否已生成")
    table_rows_ready: bool = Field(default=False, description="table_rows 是否已生成且非空")
    table_cells_generated: bool = Field(default=False, description="table_cells 是否已生成")
    table_cells_ready: bool = Field(default=False, description="table_cells 是否已生成且非空")
    updated_at: str = Field(..., description="更新时间")


class TaskListResponse(BaseModel):
    """Collection-scoped task listing payload."""

    collection_id: str = Field(..., description="集合 ID")
    count: int = Field(..., description="返回任务数量")
    items: list[TaskResponse] = Field(default_factory=list, description="任务列表")
