from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["queued", "running", "completed", "partial_success", "failed"]
PipelineMode = Literal["standard", "fast"]
TaskStage = Literal[
    "queued",
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

    mode: PipelineMode = Field(
        default="standard",
        description="Collection build pipeline mode.",
    )
    verbose: bool = Field(default=False, description="Whether to emit verbose logs")
    additional_context: dict[str, Any] | None = Field(
        default=None,
        description="Additional context passed to the pipeline state",
    )


class TaskResponse(BaseModel):
    """Task metadata returned to clients."""

    task_id: str = Field(..., description="Task ID")
    collection_id: str = Field(..., description="Collection ID")
    task_type: str = Field(..., description="Task type")
    status: TaskStatus = Field(..., description="Task status")
    current_stage: TaskStage = Field(..., description="Current task stage")
    progress_percent: int = Field(default=0, description="Progress percentage")
    progress_detail: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Human-readable progress within the current stage, such as "
            "current/total/unit/message"
        ),
    )
    output_path: str | None = Field(default=None, description="Output directory")
    errors: list[str] = Field(default_factory=list, description="Errors")
    warnings: list[str] = Field(default_factory=list, description="Warnings")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    started_at: str | None = Field(default=None, description="Start timestamp")
    finished_at: str | None = Field(default=None, description="Completion timestamp")


class ArtifactStatusResponse(BaseModel):
    """Artifact readiness payload for a task or collection."""

    task_id: str = Field(..., description="Task ID")
    collection_id: str = Field(..., description="Collection ID")
    output_path: str = Field(..., description="Output directory")
    documents_generated: bool = Field(
        default=False,
        description="Whether documents were generated",
    )
    documents_ready: bool = Field(
        default=False,
        description="Whether documents were generated and are non-empty",
    )
    document_profiles_generated: bool = Field(
        default=False,
        description="Whether document_profiles were generated",
    )
    document_profiles_ready: bool = Field(
        default=False,
        description="Whether document_profiles were generated and are non-empty",
    )
    evidence_anchors_generated: bool = Field(
        default=False,
        description="Whether evidence_anchors were generated",
    )
    evidence_anchors_ready: bool = Field(
        default=False,
        description="Whether evidence_anchors were generated and are non-empty",
    )
    method_facts_generated: bool = Field(
        default=False,
        description="Whether method_facts were generated",
    )
    method_facts_ready: bool = Field(
        default=False,
        description="Whether method_facts were generated and are non-empty",
    )
    evidence_cards_generated: bool = Field(
        default=False,
        description="Whether evidence_cards were generated",
    )
    evidence_cards_ready: bool = Field(
        default=False,
        description="Whether evidence_cards were generated and are non-empty",
    )
    characterization_observations_generated: bool = Field(
        default=False,
        description="Whether characterization_observations were generated",
    )
    characterization_observations_ready: bool = Field(
        default=False,
        description=(
            "Whether characterization_observations were generated and are non-empty"
        ),
    )
    structure_features_generated: bool = Field(
        default=False,
        description="Whether structure_features were generated",
    )
    structure_features_ready: bool = Field(
        default=False,
        description="Whether structure_features were generated and are non-empty",
    )
    test_conditions_generated: bool = Field(
        default=False,
        description="Whether test_conditions were generated",
    )
    test_conditions_ready: bool = Field(
        default=False,
        description="Whether test_conditions were generated and are non-empty",
    )
    baseline_references_generated: bool = Field(
        default=False,
        description="Whether baseline_references were generated",
    )
    baseline_references_ready: bool = Field(
        default=False,
        description="Whether baseline_references were generated and are non-empty",
    )
    sample_variants_generated: bool = Field(
        default=False,
        description="Whether sample_variants were generated",
    )
    sample_variants_ready: bool = Field(
        default=False,
        description="Whether sample_variants were generated and are non-empty",
    )
    measurement_results_generated: bool = Field(
        default=False,
        description="Whether measurement_results were generated",
    )
    measurement_results_ready: bool = Field(
        default=False,
        description="Whether measurement_results were generated and are non-empty",
    )
    comparable_results_generated: bool = Field(
        default=False,
        description="Whether comparable_results were generated",
    )
    comparable_results_ready: bool = Field(
        default=False,
        description="Whether comparable_results were generated and are non-empty",
    )
    collection_comparable_results_generated: bool = Field(
        default=False,
        description="Whether collection_comparable_results were generated",
    )
    collection_comparable_results_ready: bool = Field(
        default=False,
        description=(
            "Whether collection_comparable_results were generated and are non-empty"
        ),
    )
    collection_comparable_results_stale: bool = Field(
        default=False,
        description=(
            "Whether collection_comparable_results are stale because of "
            "policy or version drift"
        ),
    )
    comparison_rows_generated: bool = Field(
        default=False,
        description="Whether comparison_rows were generated",
    )
    comparison_rows_ready: bool = Field(
        default=False,
        description="Whether comparison_rows were generated and are non-empty",
    )
    comparison_rows_stale: bool = Field(
        default=False,
        description=(
            "Whether comparison_rows are stale because an upstream scoped "
            "artifact is stale"
        ),
    )
    graph_generated: bool = Field(
        default=False,
        description=(
            "Whether all backbone and comparison-semantic inputs required by "
            "the Core graph were generated"
        ),
    )
    graph_ready: bool = Field(
        default=False,
        description="Whether the Core graph view can be projected on demand",
    )
    graph_stale: bool = Field(
        default=False,
        description=(
            "Whether the Core graph semantic inputs are no longer current because "
            "a collection-scoped artifact is stale"
        ),
    )
    blocks_generated: bool = Field(
        default=False,
        description="Whether blocks were generated",
    )
    blocks_ready: bool = Field(
        default=False,
        description="Whether blocks were generated and are non-empty",
    )
    figures_generated: bool = Field(
        default=False,
        description="Whether figures were generated",
    )
    figures_ready: bool = Field(
        default=False,
        description="Whether figures were generated and are non-empty",
    )
    table_rows_generated: bool = Field(
        default=False,
        description="Whether table_rows were generated",
    )
    table_rows_ready: bool = Field(
        default=False,
        description="Whether table_rows were generated and are non-empty",
    )
    table_cells_generated: bool = Field(
        default=False,
        description="Whether table_cells were generated",
    )
    table_cells_ready: bool = Field(
        default=False,
        description="Whether table_cells were generated and are non-empty",
    )
    updated_at: str = Field(..., description="Last update timestamp")


class TaskListResponse(BaseModel):
    """Collection-scoped task listing payload."""

    collection_id: str = Field(..., description="Collection ID")
    count: int = Field(..., description="Number of returned tasks")
    items: list[TaskResponse] = Field(default_factory=list, description="Tasks")
