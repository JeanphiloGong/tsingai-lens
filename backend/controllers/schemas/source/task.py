from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["queued", "running", "completed", "partial_success", "failed"]
PipelineMode = Literal["standard", "fast"]
class DocumentPreparationRequest(BaseModel):
    """Request payload to prepare one collection document."""

    model_config = ConfigDict(extra="ignore")

    mode: PipelineMode = Field(
        default="standard",
        description="Document preparation mode.",
    )


class TaskResponse(BaseModel):
    """Task metadata returned to clients."""

    task_id: str = Field(..., description="Task ID")
    collection_id: str = Field(..., description="Collection ID")
    document_id: str | None = Field(default=None, description="Document ID")
    task_type: str = Field(..., description="Task type")
    mode: str = Field(..., description="Execution mode")
    input_fingerprint: str | None = Field(
        default=None,
        description="Prepared input identity",
    )
    status: TaskStatus = Field(..., description="Task status")
    current_stage: str = Field(..., description="Current task stage")
    progress_percent: int = Field(default=0, description="Progress percentage")
    progress_detail: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Human-readable progress within the current stage, such as "
            "current/total/unit/message"
        ),
    )
    errors: list[str] = Field(default_factory=list, description="Errors")
    warnings: list[str] = Field(default_factory=list, description="Warnings")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    started_at: str | None = Field(default=None, description="Start timestamp")
    finished_at: str | None = Field(default=None, description="Completion timestamp")


class TaskListResponse(BaseModel):
    """Collection-scoped task listing payload."""

    collection_id: str = Field(..., description="Collection ID")
    count: int = Field(..., description="Number of returned tasks")
    items: list[TaskResponse] = Field(default_factory=list, description="Tasks")
