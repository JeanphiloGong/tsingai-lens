from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


TaskStatus = Literal["queued", "running", "completed", "partial_success", "failed"]
TaskStage = Literal[
    "queued",
    "files_registered",
    "source_index_started",
    "source_index_completed",
    "document_profiles_started",
    "evidence_cards_started",
    "comparison_rows_started",
    "protocol_artifacts_started",
    "artifacts_ready",
    "failed",
]


class IndexTaskCreateRequest(BaseModel):
    """Request payload to start a collection index task."""

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


class TaskListResponse(BaseModel):
    """Collection-scoped task listing payload."""

    collection_id: str = Field(..., description="集合 ID")
    count: int = Field(..., description="返回任务数量")
    items: list[TaskResponse] = Field(default_factory=list, description="任务列表")
