from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AnswerMode = Literal["grounded", "hybrid", "general"]
SourceMode = Literal[
    "collection_grounded",
    "collection_limited",
    "general_fallback",
    "general_only",
]
SourceLinkKind = Literal["document", "evidence"]


class GoalSessionCreateRequest(BaseModel):
    """Create a collection-bound goal session."""

    collection_id: str = Field(..., description="Bound collection id")
    focused_material_id: str | None = Field(default=None, description="Focused material id")
    focused_paper_id: str | None = Field(default=None, description="Focused paper/document id")
    focused_objective_id: str | None = Field(default=None, description="Focused research objective id")
    focused_goal_id: str | None = Field(default=None, description="Focused confirmed goal id")
    goal_text: str | None = Field(default=None, description="User-facing research goal")
    goal_brief_json: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured goal brief context",
    )
    answer_mode: AnswerMode = Field(default="hybrid", description="Answer source mode")


class GoalSessionUpdateRequest(BaseModel):
    """Patch explicit goal session context."""

    collection_id: str | None = Field(default=None, description="Bound collection id")
    focused_material_id: str | None = Field(default=None, description="Focused material id")
    focused_paper_id: str | None = Field(default=None, description="Focused paper/document id")
    focused_objective_id: str | None = Field(default=None, description="Focused research objective id")
    focused_goal_id: str | None = Field(default=None, description="Focused confirmed goal id")
    goal_text: str | None = Field(default=None, description="User-facing research goal")
    goal_brief_json: dict[str, Any] | None = Field(
        default=None,
        description="Structured goal brief context",
    )
    answer_mode: AnswerMode | None = Field(default=None, description="Answer source mode")


class GoalSessionResponse(BaseModel):
    """Collection-bound goal session state."""

    session_id: str = Field(..., description="Goal session id")
    user_id: str = Field(..., description="Session owner")
    collection_id: str = Field(..., description="Bound collection id")
    focused_material_id: str | None = Field(default=None, description="Focused material id")
    focused_paper_id: str | None = Field(default=None, description="Focused paper/document id")
    focused_objective_id: str | None = Field(default=None, description="Focused research objective id")
    focused_goal_id: str | None = Field(default=None, description="Focused confirmed goal id")
    goal_text: str | None = Field(default=None, description="User-facing research goal")
    goal_brief_json: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured goal brief context",
    )
    answer_mode: AnswerMode = Field(..., description="Answer source mode")
    rolling_summary: str = Field(default="", description="Session rolling summary")
    last_evidence_ids: list[str] = Field(default_factory=list, description="Recent evidence ids")
    last_material_ids: list[str] = Field(default_factory=list, description="Recent material ids")
    last_paper_ids: list[str] = Field(default_factory=list, description="Recent paper ids")
    collection_data_version: str | None = Field(
        default=None,
        description="Collection artifact data version",
    )
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Update timestamp")


class GoalSessionMessageRequest(BaseModel):
    """Post one user message into a goal session."""

    message: str = Field(..., description="User message or command")
    page_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional route context such as material_id",
    )


class GoalSourceLinkResponse(BaseModel):
    """User-navigable source link for an assistant answer."""

    kind: SourceLinkKind = Field(..., description="Source link kind")
    label: str = Field(..., description="Short user-facing source label")
    href: str = Field(..., description="Frontend route for source verification")


class GoalSessionMessageResponse(BaseModel):
    """Assistant response for one goal session message."""

    message_id: str = Field(..., description="Assistant message id")
    session_id: str = Field(..., description="Goal session id")
    role: Literal["assistant"] = Field(default="assistant", description="Message role")
    answer: str = Field(..., description="Assistant answer")
    content: str = Field(..., description="Assistant answer content")
    source_mode: SourceMode = Field(..., description="Answer source boundary")
    used_evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence ids used by the answer",
    )
    warnings: list[str] = Field(default_factory=list, description="Source or readiness warnings")
    links: dict[str, str] = Field(default_factory=dict, description="Workspace links")
    source_links: list[GoalSourceLinkResponse] = Field(
        default_factory=list,
        description="User-navigable document or evidence links used by the answer",
    )
    review_gate: str | None = Field(
        default=None,
        description="Review gate satisfied by the answer, such as training_ready_findings",
    )
    created_at: str = Field(..., description="Creation timestamp")


class GoalSessionMessageListResponse(BaseModel):
    """List stored messages for a goal session."""

    session_id: str = Field(..., description="Goal session id")
    items: list[dict[str, Any]] = Field(default_factory=list, description="Stored messages")
