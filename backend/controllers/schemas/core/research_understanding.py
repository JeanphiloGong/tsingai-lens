from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


UnderstandingState = Literal["empty", "partial", "ready", "limited"]
UnderstandingScopeType = Literal["collection", "material", "objective", "goal", "document"]
ClaimStatus = Literal["supported", "limited", "conflicted", "unsupported"]
ClaimType = Literal[
    "finding",
    "measurement",
    "comparison",
    "mechanism",
    "limitation",
    "context",
]
RelationType = Literal[
    "improves",
    "reduces",
    "increases",
    "decreases",
    "correlates",
    "explains",
    "conflicts",
    "compares",
]
ResearchUnderstandingFeedbackStatus = Literal["correct", "incorrect", "partial", "unclear"]
ResearchUnderstandingFeedbackIssueType = Literal[
    "none",
    "evidence_not_grounded",
    "missing_evidence",
    "wrong_context",
    "wrong_relation",
    "overclaim",
    "unclear_statement",
    "other",
]


class ResearchUnderstandingScopeResponse(BaseModel):
    """Scope bound to one research-understanding projection."""

    scope_type: str = Field(
        ...,
        description="collection, material, objective, goal, or document",
    )
    collection_id: str = Field(..., description="Collection ID")
    goal_id: str | None = Field(default=None, description="Optional confirmed goal scope")
    material_id: str | None = Field(default=None, description="Optional material scope")
    objective_id: str | None = Field(default=None, description="Optional objective scope")
    document_id: str | None = Field(default=None, description="Optional document scope")
    title: str | None = Field(default=None, description="User-facing scope title")


class ResearchEvidenceRefResponse(BaseModel):
    """Traceable evidence reference used by claims and relations."""

    evidence_ref_id: str = Field(..., description="Stable evidence reference ID")
    source_kind: str = Field(..., description="table, figure, text, or unknown")
    document_id: str | None = Field(default=None, description="Source document ID")
    label: str = Field(..., description="User-facing evidence label")
    locator: dict[str, Any] = Field(default_factory=dict, description="Source locator")
    fact_ids: list[str] = Field(default_factory=list, description="Underlying fact IDs")
    anchor_ids: list[str] = Field(default_factory=list, description="Source anchor IDs")
    confidence: float | None = Field(default=None, description="Evidence confidence")
    traceability_status: str = Field(..., description="Traceability status")
    quote: str | None = Field(default=None, description="Optional quoted source text")
    href: str | None = Field(default=None, description="Optional source navigation URL")


class ResearchContextResponse(BaseModel):
    """Context constraining where a claim or relation applies."""

    context_id: str = Field(..., description="Stable context ID")
    label: str = Field(..., description="User-facing context label")
    material_scope: list[str] = Field(default_factory=list)
    process_context: dict[str, Any] = Field(default_factory=dict)
    test_condition: dict[str, Any] = Field(default_factory=dict)
    property_scope: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ResearchClaimResponse(BaseModel):
    """Evidence-backed research claim."""

    claim_id: str = Field(..., description="Stable claim ID")
    claim_type: ClaimType = Field(..., description="Claim type")
    statement: str = Field(..., description="Claim statement")
    status: ClaimStatus = Field(..., description="Support status")
    confidence: float | None = Field(default=None)
    strength: str | None = Field(default=None)
    evidence_ref_ids: list[str] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)
    source_object_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResearchRelationResponse(BaseModel):
    """Evidence-backed relation between research objects."""

    relation_id: str = Field(..., description="Stable relation ID")
    relation_type: RelationType = Field(..., description="Relation type")
    subject: str = Field(..., description="Relation subject")
    predicate: str = Field(..., description="Relation predicate or direction")
    object: str = Field(..., description="Relation object")
    status: ClaimStatus = Field(..., description="Support status")
    confidence: float | None = Field(default=None)
    evidence_ref_ids: list[str] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)
    source_object_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResearchUnderstandingSummaryResponse(BaseModel):
    """Count summary for the projection."""

    claim_count: int = Field(default=0)
    relation_count: int = Field(default=0)
    evidence_ref_count: int = Field(default=0)
    context_count: int = Field(default=0)


class ResearchUnderstandingResponse(BaseModel):
    """Claim / relation / evidence / context projection for review and AI grounding."""

    schema_version: str = Field(..., description="Research understanding schema version")
    state: UnderstandingState = Field(..., description="Projection readiness state")
    scope: ResearchUnderstandingScopeResponse
    claims: list[ResearchClaimResponse] = Field(default_factory=list)
    relations: list[ResearchRelationResponse] = Field(default_factory=list)
    evidence_refs: list[ResearchEvidenceRefResponse] = Field(default_factory=list)
    contexts: list[ResearchContextResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: ResearchUnderstandingSummaryResponse = Field(
        default_factory=ResearchUnderstandingSummaryResponse
    )


class ResearchUnderstandingFeedbackCreateRequest(BaseModel):
    """Expert feedback captured on one research-understanding claim."""

    model_config = ConfigDict(extra="ignore")

    scope_type: UnderstandingScopeType
    scope_id: str = Field(..., min_length=1, max_length=160)
    claim_id: str = Field(..., min_length=1, max_length=200)
    review_status: ResearchUnderstandingFeedbackStatus
    issue_type: ResearchUnderstandingFeedbackIssueType = Field(default="none")
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)


class ResearchUnderstandingFeedbackResponse(BaseModel):
    """Persisted expert feedback on one claim."""

    feedback_id: str
    collection_id: str
    scope_type: str
    scope_id: str
    claim_id: str
    review_status: ResearchUnderstandingFeedbackStatus
    issue_type: ResearchUnderstandingFeedbackIssueType
    note: str | None = None
    reviewer: str | None = None
    created_at: str


class ResearchUnderstandingFeedbackListResponse(BaseModel):
    """Collection-bound research-understanding feedback list."""

    collection_id: str
    items: list[ResearchUnderstandingFeedbackResponse] = Field(default_factory=list)


class ResearchUnderstandingCurationCreateRequest(BaseModel):
    """Expert-curated correction for one research-understanding claim."""

    model_config = ConfigDict(extra="ignore")

    scope_type: UnderstandingScopeType
    scope_id: str = Field(..., min_length=1, max_length=160)
    claim_id: str = Field(..., min_length=1, max_length=200)
    curated_claim_type: ClaimType
    curated_status: ClaimStatus
    curated_statement: str = Field(..., min_length=1, max_length=4000)
    curated_evidence_ref_ids: list[str] = Field(default_factory=list, max_length=80)
    curated_context_ids: list[str] = Field(default_factory=list, max_length=80)
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)


class ResearchUnderstandingCurationResponse(BaseModel):
    """Persisted expert-curated claim correction."""

    curation_id: str
    collection_id: str
    scope_type: str
    scope_id: str
    claim_id: str
    curated_claim_type: ClaimType
    curated_status: ClaimStatus
    curated_statement: str
    curated_evidence_ref_ids: list[str] = Field(default_factory=list)
    curated_context_ids: list[str] = Field(default_factory=list)
    note: str | None = None
    reviewer: str | None = None
    updated_at: str


class ResearchUnderstandingCurationListResponse(BaseModel):
    """Collection-bound research-understanding claim curation list."""

    collection_id: str
    items: list[ResearchUnderstandingCurationResponse] = Field(default_factory=list)
