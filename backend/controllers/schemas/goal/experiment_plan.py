from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ExperimentPlanStatus = Literal["draft", "ready_for_review", "archived"]
ExperimentPlanSourceLinkKind = Literal["document", "evidence"]


class ExperimentPlanSourceLink(BaseModel):
    kind: ExperimentPlanSourceLinkKind
    label: str = Field(..., min_length=1, max_length=80)
    href: str = Field(..., min_length=1, max_length=2000)


class ExperimentPlanCreateRequest(BaseModel):
    """Save one goal-scoped experiment plan draft."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., min_length=1, max_length=400)
    content: str = Field(..., min_length=1, max_length=20000)
    source_message_id: str | None = Field(default=None, max_length=200)
    source_links: list[ExperimentPlanSourceLink] = Field(
        default_factory=list,
        max_length=20,
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentPlanUpdateRequest(BaseModel):
    """Edit a saved experiment plan draft."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., min_length=1, max_length=400)
    content: str = Field(..., min_length=1, max_length=20000)
    status: ExperimentPlanStatus = "draft"


class ExperimentPlanResponse(BaseModel):
    plan_id: str
    collection_id: str
    goal_id: str
    title: str
    content: str
    status: ExperimentPlanStatus
    source_message_id: str | None = None
    source_links: list[ExperimentPlanSourceLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: str
    updated_at: str


class ExperimentPlanListResponse(BaseModel):
    collection_id: str
    goal_id: str
    items: list[ExperimentPlanResponse] = Field(default_factory=list)
