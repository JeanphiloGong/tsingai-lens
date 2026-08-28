from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


GoalIntent = Literal["explore", "compare", "design_experiment"]
CoverageLevel = Literal["direct", "indirect", "sparse", "absent"]
EntryMode = Literal["comparison", "exploratory"]


class GoalIntakeRequest(BaseModel):
    """Request payload for goal-driven collection seeding."""

    material_system: str | None = Field(
        default=None, description="Target material system"
    )
    target_property: str | None = Field(default=None, description="Target property")
    intent: GoalIntent = Field(default="explore", description="Research intent")
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Research constraints",
    )
    context: str | None = Field(default=None, description="Additional context")
    max_seed_documents: int = Field(
        default=30,
        ge=1,
        le=200,
        description="Maximum number of candidate documents",
    )


class ResearchBriefResponse(BaseModel):
    """Structured goal brief produced by Goal Brief / Intake."""

    material_system: str | None = Field(
        default=None, description="Target material system"
    )
    target_property: str | None = Field(default=None, description="Target property")
    intent: GoalIntent = Field(..., description="Research intent")
    objective: str = Field(..., description="Structured research objective")
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Research constraints",
    )
    context: str | None = Field(default=None, description="Additional context")


class CoverageAssessmentResponse(BaseModel):
    """Coarse intake-side coverage hint before entering Core artifacts."""

    level: CoverageLevel = Field(..., description="Evidence coverage level")
    rationale: str | None = Field(default=None, description="Coverage rationale")
    direct_evidence_count: int = Field(
        default=0,
        ge=0,
        description="Estimated direct evidence count",
    )
    indirect_evidence_count: int = Field(
        default=0,
        ge=0,
        description="Estimated indirect evidence count",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Coverage risk warnings",
    )


class SeedCollectionResponse(BaseModel):
    """Collection created for the research brief."""

    collection_id: str = Field(..., description="Target collection ID")
    name: str = Field(..., description="Collection name")
    created: bool = Field(default=True, description="Whether a collection was created")
    seeded_document_count: int = Field(
        default=0,
        ge=0,
        description="Number of seeded candidate documents",
    )
    source_channels: list[str] = Field(
        default_factory=list,
        description="Candidate source channels",
    )


class EntryRecommendationResponse(BaseModel):
    """Next-step recommendation after goal intake."""

    recommended_mode: EntryMode = Field(..., description="Recommended entry mode")
    reason: str = Field(..., description="Recommendation rationale")
    next_actions: list[str] = Field(
        default_factory=list,
        description="Recommended next actions",
    )
    links: list[str] = Field(default_factory=list, description="Recommended links")


class GoalIntakeResponse(BaseModel):
    """Goal Brief / Intake response contract without Core artifact payloads."""

    research_brief: ResearchBriefResponse = Field(..., description="Research brief")
    coverage_assessment: CoverageAssessmentResponse = Field(
        ...,
        description="Coverage assessment",
    )
    seed_collection: SeedCollectionResponse = Field(
        ...,
        description="Collection seeding result",
    )
    entry_recommendation: EntryRecommendationResponse = Field(
        ...,
        description="Entry recommendation",
    )
