from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


PipelineRunStatus = Literal[
    "queued", "running", "completed", "partial_success", "failed"
]
PipelineNodeStatus = Literal["queued", "running", "succeeded", "failed", "skipped"]


class PipelineNodeResponse(BaseModel):
    name: str = Field(..., description="Stable pipeline node name")
    dependencies: list[str] = Field(default_factory=list)
    status: PipelineNodeStatus
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    timestamps: dict[str, str | None] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)


class PipelineRunSummaryResponse(BaseModel):
    """Compact execution state used to locate and monitor collection runs."""

    run_id: str = Field(..., description="Stable pipeline run ID")
    pipeline_name: str = Field(..., description="Stable pipeline name")
    scope_type: str = Field(..., description="Execution scope kind")
    scope_id: str = Field(..., description="Execution scope ID")
    status: PipelineRunStatus = Field(..., description="Run lifecycle status")
    current_node: str | None = Field(default=None, description="Current phase or node")
    progress_percent: int = Field(default=0, ge=0, le=100)
    progress_detail: dict[str, Any] | None = Field(default=None)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    updated_at: str = Field(..., description="Last update timestamp")


class PipelineRunResponse(PipelineRunSummaryResponse):
    """Complete technical execution state for one pipeline invocation."""

    collection_id: str = Field(..., description="Owning Collection ID")
    mode: str = Field(..., description="Execution mode")
    input_fingerprint: str | None = Field(
        default=None,
        description="Identity of the input state consumed by this run",
    )
    nodes: dict[str, PipelineNodeResponse] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    resumed_from_run_id: str | None = Field(default=None)
    created_at: str = Field(..., description="Creation timestamp")
    started_at: str | None = Field(default=None, description="Start timestamp")
    finished_at: str | None = Field(default=None, description="Completion timestamp")


class PipelineRunListResponse(BaseModel):
    collection_id: str = Field(..., description="Owning Collection ID")
    count: int = Field(..., description="Number of returned runs")
    items: list[PipelineRunSummaryResponse] = Field(default_factory=list)


__all__ = [
    "PipelineNodeResponse",
    "PipelineNodeStatus",
    "PipelineRunListResponse",
    "PipelineRunResponse",
    "PipelineRunSummaryResponse",
    "PipelineRunStatus",
]
