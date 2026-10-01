"""Response models used only by the research-objective route module."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from controllers.schemas.core.research_objectives import (
    AnalysisStatus,
    EvidenceAttributionScope,
    EvidenceResultDirection,
    EvidenceStatus,
    FindingResponse,
    ObjectiveAnalysisStateResponse,
    ObjectiveEvidenceResponse,
)

ConfirmationStatus = Literal["candidate", "confirmed"]


ObjectiveOrigin = Literal["system_discovered", "chat_assisted"]


ObjectiveScopeClassification = Literal[
    "likely_relevant",
    "needs_inspection",
    "confidently_out_of_scope",
]


class ObjectiveSummaryResponse(BaseModel):
    collection_id: str
    objective_id: str
    question: str
    material_scope: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    mechanisms: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    requested_comparator: str | None = None
    seed_document_ids: list[str] = Field(default_factory=list)
    excluded_document_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str | None = None
    source_relationship_ids: list[str] = Field(default_factory=list)
    parent_objective_id: str | None = None
    parent_analysis_version: int | None = Field(default=None, ge=1)
    derivation_basis: list[dict[str, Any]] = Field(default_factory=list)
    confirmation_status: ConfirmationStatus
    active_analysis_version: int | None = None
    published_analysis_version: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    origin: ObjectiveOrigin = "system_discovered"
    created_by_user_id: str | None = None
    created_by_tool_call_id: str | None = None


class RankedObjectiveSummaryResponse(ObjectiveSummaryResponse):
    rank: int = Field(..., ge=1)


class PaginatedObjectiveListResponse(BaseModel):
    collection_id: str
    objectives: list[RankedObjectiveSummaryResponse] = Field(default_factory=list)
    offset: int = Field(..., ge=0)
    limit: int | None = Field(default=None, ge=1)
    total: int = Field(..., ge=0)


class ObjectiveScopeCountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    likely_relevant: int = Field(..., ge=0)
    needs_inspection: int = Field(..., ge=0)
    confidently_out_of_scope: int = Field(..., ge=0)


class ObjectiveScopeDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    classification: ObjectiveScopeClassification
    reason: str
    doc_role: str
    map_status: str
    map_limitations: list[str] = Field(default_factory=list)
    support_basis: list[str] = Field(default_factory=list)
    is_seed: bool = False


class ObjectiveScopeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str
    objective_id: str
    counts: ObjectiveScopeCountsResponse
    recommended_document_ids: list[str] = Field(default_factory=list)
    review_document_ids: list[str] = Field(default_factory=list)
    excluded_document_ids: list[str] = Field(default_factory=list)
    decisions: list[ObjectiveScopeDecisionResponse] = Field(default_factory=list)
    support_is_evidence: bool = False


class ObjectiveAnalysisStatusResponse(BaseModel):
    """Small progress payload used while an Objective analysis is running."""

    collection_id: str
    objective_id: str
    analysis_version: int | None = Field(default=None, ge=1)
    status: AnalysisStatus | None = None
    phase: str | None = None
    processed_document_count: int = Field(default=0, ge=0)
    total_document_count: int = Field(default=0, ge=0)
    current_document_id: str | None = None
    progress_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class ObjectiveEvidenceGapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    document_id: str
    source_kind: str
    source_ref: str
    page_numbers: list[int] = Field(default_factory=list)
    evidence_status: EvidenceStatus
    reason: str
    outcome: str | None = None
    source_excerpt: str = ""


class ObjectiveEvidenceReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_evidence_count: int = Field(..., ge=0)
    result_count: int = Field(..., ge=0)
    comparable_evidence_count: int = Field(..., ge=0)
    gap_count: int = Field(..., ge=0)
    omitted_gap_count: int = Field(..., ge=0)
    status_counts: dict[EvidenceStatus, int] = Field(default_factory=dict)
    gaps: list[ObjectiveEvidenceGapResponse] = Field(default_factory=list)


class ObjectiveEvidenceMapObjectiveNodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["objective"]
    label: str
    objective_id: str
    question: str
    material_scope: list[str]
    variables: list[str]
    outcomes: list[str]


class ObjectiveEvidenceMapFindingNodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["finding"]
    label: str
    finding_id: str
    statement: str
    factors: list[str]
    outcome: str
    direction: EvidenceResultDirection
    assertion_strength: Literal["causal", "associative", "descriptive"]
    synthesis_status: Literal[
        "single_study",
        "agreement",
        "conflict",
        "condition_dependent",
        "insufficient_confirmation",
    ]
    certainty: float = Field(..., ge=0, le=1)
    limitations: list[str]


class ObjectiveEvidenceMapEvidenceNodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["evidence"]
    label: str
    evidence_id: str
    document_id: str
    evidence_role: str
    attribution_scope: EvidenceAttributionScope
    evidence_status: EvidenceStatus | None = None
    evidence_status_reason: str | None = None
    confidence: float = Field(..., ge=0, le=1)
    direction: EvidenceResultDirection | None = None
    outcome: str | None = None
    source_excerpt: str


class ObjectiveEvidenceMapSourceNodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["source"]
    label: str
    document_id: str
    source_kind: str
    source_ref: str
    source_excerpt: str
    page_numbers: list[int]
    evidence_ids: list[str]


class ObjectiveEvidenceMapDocumentNodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["document"]
    label: str
    document_id: str
    analysis_status: Literal["pending", "analyzed", "excluded", "failed"]
    evidence_disposition: (
        Literal[
            "excluded",
            "no_routable_evidence",
            "coverage_incomplete",
            "extraction_failed",
            "no_comparable_evidence",
            "comparable_evidence",
        ]
        | None
    ) = None
    evidence_disposition_reason: str | None = None


ObjectiveEvidenceMapNodeResponse = Annotated[
    ObjectiveEvidenceMapObjectiveNodeResponse
    | ObjectiveEvidenceMapFindingNodeResponse
    | ObjectiveEvidenceMapEvidenceNodeResponse
    | ObjectiveEvidenceMapSourceNodeResponse
    | ObjectiveEvidenceMapDocumentNodeResponse,
    Field(discriminator="type"),
]


class ObjectiveEvidenceMapEdgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    target: str
    relation: Literal[
        "has_finding",
        "supports",
        "contradicts",
        "contextualizes",
        "extracted_from",
        "reported_in",
        "includes_document",
    ]
    condition_boundary: bool = False


class ObjectiveEvidenceMapCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_document_count: int = Field(..., ge=0)
    analyzed_document_count: int = Field(..., ge=0)
    excluded_document_count: int = Field(..., ge=0)
    failed_document_count: int = Field(..., ge=0)
    direct_evidence_document_count: int = Field(..., ge=0)
    finding_count: int = Field(..., ge=0)
    evidence_count: int = Field(..., ge=0)
    source_count: int = Field(..., ge=0)
    unlinked_evidence_count: int = Field(..., ge=0)
    evidence_status_counts: dict[EvidenceStatus, int] = Field(default_factory=dict)


class ObjectiveEvidenceMapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str
    objective_id: str
    analysis_version: int = Field(..., ge=1)
    projection_version: Literal["objective-evidence-map.v1"]
    complete: bool = Field(
        ...,
        description=(
            "Whether every included paper reached a non-technical analysis outcome."
        ),
    )
    nodes: list[ObjectiveEvidenceMapNodeResponse]
    edges: list[ObjectiveEvidenceMapEdgeResponse]
    coverage: ObjectiveEvidenceMapCoverageResponse


class InspectedObjectiveSourceRefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["text_window", "table", "figure"]
    source_ref: str
    source_digest: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class PaperContributionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str
    objective_id: str
    analysis_version: int = Field(..., ge=1)
    document_id: str
    analysis_status: Literal["pending", "analyzed", "excluded", "failed"]
    relevance: Literal["high", "medium", "low", "irrelevant", "uncertain"]
    paper_role: Literal[
        "primary_experiment",
        "supporting_method",
        "supporting_background",
        "review",
        "modeling_only",
        "irrelevant",
        "mixed",
        "uncertain",
    ]
    contribution_summary: str | None = None
    material_match: list[str] = Field(default_factory=list)
    changed_variables: list[str] = Field(default_factory=list)
    measured_property_scope: list[str] = Field(default_factory=list)
    test_environment_scope: list[str] = Field(default_factory=list)
    exclusion_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)
    evidence_disposition: (
        Literal[
            "excluded",
            "no_routable_evidence",
            "no_grounded_evidence",
            "coverage_incomplete",
            "extraction_failed",
            "no_comparable_evidence",
            "comparable_evidence",
        ]
        | None
    ) = None
    routed_source_count: int | None = Field(default=None, ge=0)
    extracted_source_count: int | None = Field(default=None, ge=0)
    comparable_evidence_count: int | None = Field(default=None, ge=0)
    failed_source_count: int | None = Field(default=None, ge=0)
    uninspected_source_count: int | None = Field(default=None, ge=0)
    evidence_disposition_reason: str | None = None
    evidence_status_counts: dict[EvidenceStatus, int] = Field(default_factory=dict)
    inspected_source_refs: list[InspectedObjectiveSourceRefResponse] = Field(
        default_factory=list
    )


class ObjectiveAnalysisResponse(BaseModel):
    collection_id: str
    objective: ObjectiveSummaryResponse
    active_analysis: ObjectiveAnalysisStateResponse | None = None
    published_analysis: ObjectiveAnalysisStateResponse | None = None
    paper_contributions: list[PaperContributionResponse] = Field(default_factory=list)
    evidence_review: ObjectiveEvidenceReviewResponse = Field(
        default_factory=lambda: ObjectiveEvidenceReviewResponse(
            total_evidence_count=0,
            result_count=0,
            comparable_evidence_count=0,
            gap_count=0,
            omitted_gap_count=0,
        )
    )
    warnings: list[str] = Field(default_factory=list)


class FindingEvidenceReviewResponse(BaseModel):
    needs_review: bool
    evidence_replacements: dict[str, str | None] = Field(default_factory=dict)


class FindingListResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    items: list[FindingResponse] = Field(default_factory=list)
    evidence_reviews: dict[str, FindingEvidenceReviewResponse] = Field(
        default_factory=dict
    )
    offset: int
    limit: int
    total: int


class FindingSummaryReferenceResponse(BaseModel):
    id: str
    kind: Literal["finding", "evidence"]
    label: str
    document_id: str | None = None
    source_ref: str | None = None
    source_kind: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    source_excerpt: str | None = None


class FindingSummaryResponse(BaseModel):
    collection_id: str
    objective_id: str
    finding_id: str
    analysis_version: int
    language: Literal["en", "zh"]
    text: str
    citation_ids: list[str]
    references: list[FindingSummaryReferenceResponse]
    model: str
    prompt_version: str
    generated_at: str


class FindingDetailResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    finding: FindingResponse
    evidence_review: FindingEvidenceReviewResponse


class ObjectiveEvidenceListResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str | None = None
    items: list[ObjectiveEvidenceResponse] = Field(default_factory=list)
    offset: int
    limit: int
    total: int
