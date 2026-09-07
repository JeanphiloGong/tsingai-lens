from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from application.goal.research_plan_contract import ResearchPlanStructure


ExperimentPlanStatus = Literal["draft", "ready_for_review", "archived"]
ExperimentPlanSourceLinkKind = Literal["document", "evidence"]


class ExperimentPlanSourceLink(BaseModel):
    kind: ExperimentPlanSourceLinkKind
    label: str = Field(..., min_length=1, max_length=80)
    href: str = Field(..., min_length=1, max_length=2000)


class ExperimentPlanCreateRequest(BaseModel):
    """Save one manual Objective-scoped experiment plan draft."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=400)
    content: str = Field(..., min_length=1, max_length=20000)
    structured_plan: ResearchPlanStructure | None = None


class ExperimentPlanUpdateRequest(BaseModel):
    """Edit a saved experiment plan draft."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=400)
    content: str = Field(..., min_length=1, max_length=20000)
    status: ExperimentPlanStatus = "draft"
    structured_plan: ResearchPlanStructure | None = None


class ExperimentPlanResponse(BaseModel):
    plan_id: str
    collection_id: str
    objective_id: str
    title: str
    content: str
    status: ExperimentPlanStatus
    source_message_id: str | None = None
    source_links: list[ExperimentPlanSourceLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: str
    updated_at: str
    plan_version: int = Field(default=1, ge=1)
    parent_plan_id: str | None = None
    structured_plan: dict[str, Any] | None = None
    updated_by: str | None = None


class ExperimentPlanListResponse(BaseModel):
    collection_id: str
    objective_id: str
    items: list[ExperimentPlanResponse] = Field(default_factory=list)
