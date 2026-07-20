from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from controllers.schemas.core.research_view import (
    ResearchViewState,
    ResearchViewWarningResponse,
)
from controllers.schemas.core.research_understanding import (
    ResearchUnderstandingResponse,
)


ObjectiveStatus = Literal[
    "candidate",
    "confirmed",
    "queued",
    "running",
    "ready",
    "failed",
]


class ObjectiveReviewSummaryResponse(BaseModel):
    primary_finding_count: int = 0
    review_candidate_count: int = 0


class ObjectiveWorkspaceReadinessResponse(BaseModel):
    """Readiness flags for objective-scoped workspace sections."""

    objectives_ready: bool = Field(..., description="Whether objectives were built")
    frames_ready: bool = Field(..., description="Whether paper frames are available")
    routes_ready: bool = Field(..., description="Whether evidence routes are available")
    evidence_units_ready: bool = Field(
        ...,
        description="Whether resolved evidence units are available",
    )
    logic_chain_ready: bool = Field(
        ...,
        description="Whether an objective logic chain is available",
    )


class ObjectiveSummaryResponse(BaseModel):
    """Research objective summary."""

    objective_id: str = Field(..., description="Stable objective ID")
    question: str = Field(..., description="Question-shaped research objective")
    material_scope: list[str] = Field(default_factory=list, description="Material scope")
    process_axes: list[str] = Field(default_factory=list, description="Process axes")
    property_axes: list[str] = Field(default_factory=list, description="Property axes")
    comparison_intent: str | None = Field(default=None, description="Comparison intent")
    confidence: float = Field(default=0.0, description="Objective confidence")
    status: ObjectiveStatus = "candidate"
    analysis_error: str | None = None
    analysis_progress: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ObjectiveListItemResponse(ObjectiveSummaryResponse):
    """Research objective row for collection lists."""

    state: ResearchViewState = Field(..., description="Objective workspace state")
    review_summary: ObjectiveReviewSummaryResponse
    paper_frame_count: int = Field(default=0, description="Paper frame count")
    evidence_route_count: int = Field(default=0, description="Evidence route count")
    evidence_unit_count: int = Field(default=0, description="Evidence unit count")
    logic_chain_count: int = Field(default=0, description="Logic chain count")


class ObjectiveContextResponse(BaseModel):
    """Objective routing and extraction context."""

    objective_id: str = Field(..., description="Stable objective ID")
    question: str = Field(..., description="Question-shaped research objective")
    material_scope: list[str] = Field(default_factory=list, description="Material scope")
    variable_process_axes: list[str] = Field(
        default_factory=list,
        description="Process axes that vary across compared evidence",
    )
    process_context_axes: list[str] = Field(
        default_factory=list,
        description="Process axes that define fixed context",
    )
    target_property_axes: list[str] = Field(
        default_factory=list,
        description="Target property axes",
    )
    excluded_property_axes: list[str] = Field(
        default_factory=list,
        description="Property axes excluded for this objective",
    )
    routing_hints: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Source routing hints",
    )
    extraction_guidance: dict[str, Any] = Field(
        default_factory=dict,
        description="Objective-specific extraction guidance",
    )
    confidence: float = Field(default=0.0, description="Context confidence")


class ObjectivePaperFrameResponse(BaseModel):
    """Paper contribution frame under one research objective."""

    frame_id: str = Field(..., description="Stable frame ID")
    objective_id: str = Field(..., description="Stable objective ID")
    document_id: str = Field(..., description="Source document ID")
    title: str | None = Field(default=None, description="Document title")
    source_filename: str | None = Field(default=None, description="Source filename")
    relevance: str = Field(..., description="Objective relevance")
    paper_role: str = Field(..., description="Role of this paper for the objective")
    background: str | None = Field(default=None, description="Paper-specific background")
    material_match: list[str] = Field(default_factory=list, description="Matched materials")
    changed_variables: list[str] = Field(
        default_factory=list,
        description="Changed variables",
    )
    measured_property_scope: list[str] = Field(
        default_factory=list,
        description="Measured property scope",
    )
    test_environment_scope: list[str] = Field(
        default_factory=list,
        description="Test environment scope",
    )
    relevant_sections: list[str] = Field(
        default_factory=list,
        description="Relevant section labels",
    )
    relevant_tables: list[str] = Field(default_factory=list, description="Relevant table IDs")
    excluded_tables: list[str] = Field(default_factory=list, description="Excluded table IDs")


class ObjectiveEvidenceRouteResponse(BaseModel):
    """Objective-scoped source route."""

    route_id: str = Field(..., description="Stable route ID")
    objective_id: str = Field(..., description="Stable objective ID")
    document_id: str = Field(..., description="Source document ID")
    source_kind: str = Field(..., description="Source kind")
    source_ref: str = Field(..., description="Source block, table, or figure ID")
    role: str = Field(..., description="Route role")
    extractable: bool = Field(..., description="Whether this route should be extracted")
    reason: str | None = Field(default=None, description="Routing rationale")
    table_schema: dict[str, Any] = Field(default_factory=dict, description="Table schema")
    column_roles: dict[str, Any] = Field(default_factory=dict, description="Column roles")
    join_keys: dict[str, Any] = Field(default_factory=dict, description="Join keys")
    join_plan: dict[str, Any] = Field(default_factory=dict, description="Join plan")
    confidence: float = Field(default=0.0, description="Routing confidence")


class ObjectiveEvidenceUnitResponse(BaseModel):
    """Resolved objective-scoped evidence unit."""

    evidence_unit_id: str = Field(..., description="Stable evidence unit ID")
    objective_id: str = Field(..., description="Stable objective ID")
    document_id: str = Field(..., description="Source document ID")
    unit_kind: str = Field(..., description="Evidence unit kind")
    property_normalized: str | None = Field(
        default=None,
        description="Normalized property",
    )
    material_system: dict[str, Any] = Field(default_factory=dict)
    sample_context: dict[str, Any] = Field(default_factory=dict)
    process_context: dict[str, Any] = Field(default_factory=dict)
    resolved_condition: dict[str, Any] = Field(default_factory=dict)
    test_condition: dict[str, Any] = Field(default_factory=dict)
    value_payload: dict[str, Any] = Field(default_factory=dict)
    unit: str | None = Field(default=None)
    baseline_context: dict[str, Any] = Field(default_factory=dict)
    interpretation: str | None = Field(default=None)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_anchor_ids: list[str] = Field(default_factory=list)
    join_keys: dict[str, Any] = Field(default_factory=dict)
    resolution_status: str = Field(..., description="Resolution status")
    confidence: float = Field(default=0.0)


class ObjectiveLogicChainResponse(BaseModel):
    """Objective logic chain response."""

    logic_chain_id: str = Field(..., description="Stable logic chain ID")
    objective_id: str = Field(..., description="Stable objective ID")
    chain_scope: str = Field(..., description="Logic chain scope")
    document_id: str | None = Field(default=None, description="Optional document ID")
    question: str | None = Field(default=None, description="Logic chain question")
    evidence_unit_ids: list[str] = Field(default_factory=list)
    chain_payload: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = Field(default=None)
    confidence: float = Field(default=0.0)


class ObjectiveListResponse(BaseModel):
    """Collection research objective list."""

    collection_id: str = Field(..., description="Collection ID")
    state: ResearchViewState = Field(..., description="Objective list state")
    readiness: ObjectiveWorkspaceReadinessResponse
    objectives: list[ObjectiveListItemResponse] = Field(default_factory=list)
    warnings: list[ResearchViewWarningResponse] = Field(default_factory=list)


class ObjectiveResearchViewResponse(BaseModel):
    """Objective workspace response."""

    collection_id: str = Field(..., description="Collection ID")
    state: ResearchViewState = Field(..., description="Objective workspace state")
    objective: ObjectiveSummaryResponse
    review_summary: ObjectiveReviewSummaryResponse
    objective_context: ObjectiveContextResponse | None = Field(default=None)
    readiness: ObjectiveWorkspaceReadinessResponse
    paper_frames: list[ObjectivePaperFrameResponse] = Field(default_factory=list)
    evidence_routes: list[ObjectiveEvidenceRouteResponse] = Field(default_factory=list)
    evidence_units: list[ObjectiveEvidenceUnitResponse] = Field(default_factory=list)
    logic_chain: ObjectiveLogicChainResponse | None = Field(default=None)
    understanding: ResearchUnderstandingResponse | None = Field(
        default=None,
        description="Claim/relation/evidence/context projection for review and AI grounding",
    )
    existing_comparison_rows: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[ResearchViewWarningResponse] = Field(default_factory=list)


class ObjectiveAnalysisResponse(BaseModel):
    collection_id: str
    objective: ObjectiveSummaryResponse
    understanding: ResearchUnderstandingResponse | None = None
    warnings: list[str] = Field(default_factory=list)
