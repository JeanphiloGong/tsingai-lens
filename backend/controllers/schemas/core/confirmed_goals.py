from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ConfirmedGoalSourceType = Literal["user_input", "objective_candidate", "benchmark"]
ConfirmedGoalStatus = Literal["pending", "running", "ready", "failed"]


class ConfirmedGoalCreateRequest(BaseModel):
    """Create one confirmed research question for goal-driven analysis."""

    model_config = ConfigDict(extra="ignore")

    question: str = Field(..., min_length=1, max_length=4000)
    source_type: ConfirmedGoalSourceType = "user_input"
    material_hints: list[str] = Field(default_factory=list, max_length=80)
    process_hints: list[str] = Field(default_factory=list, max_length=80)
    property_hints: list[str] = Field(default_factory=list, max_length=80)
    source_objective_id: str | None = Field(default=None, max_length=200)


class ConfirmedGoalResponse(BaseModel):
    """Persisted confirmed goal returned to clients."""

    goal_id: str
    collection_id: str
    question: str
    source_type: ConfirmedGoalSourceType
    material_hints: list[str] = Field(default_factory=list)
    process_hints: list[str] = Field(default_factory=list)
    property_hints: list[str] = Field(default_factory=list)
    source_objective_id: str | None = None
    status: ConfirmedGoalStatus
    analysis_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ConfirmedGoalListResponse(BaseModel):
    """Collection-bound confirmed goal list."""

    collection_id: str
    goals: list[ConfirmedGoalResponse] = Field(default_factory=list)
