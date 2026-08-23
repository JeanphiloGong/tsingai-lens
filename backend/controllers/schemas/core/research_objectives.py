from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ConfirmationStatus = Literal["candidate", "confirmed"]
AnalysisStatus = Literal["queued", "running", "succeeded", "failed"]
ObjectiveOrigin = Literal["system_discovered", "chat_assisted"]
EvidenceAttributionScope = Literal[
    "isolated_effect",
    "joint_effect",
    "association_only",
    "descriptive_only",
    "not_attributable",
]
EvidenceResultDirection = Literal[
    "increase",
    "decrease",
    "improve",
    "worsen",
    "changed",
    "no_change",
    "mixed",
    "unknown",
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
    confirmation_status: ConfirmationStatus
    active_analysis_version: int | None = None
    published_analysis_version: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    origin: ObjectiveOrigin = "system_discovered"
    source_build_id: str | None = None
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


class TokenUsageResponse(BaseModel):
    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)


class ModelUsageResponse(BaseModel):
    model_name: str
    request_count: int = Field(..., ge=0)
    token_usage: TokenUsageResponse | None = None
    unreported_request_count: int = Field(default=0, ge=0)


class ExecutionStatsResponse(BaseModel):
    duration_ms: int | None = Field(default=None, ge=0)
    token_usage: TokenUsageResponse | None = None
    model_usage: list[ModelUsageResponse] = Field(default_factory=list)
    unreported_request_count: int = Field(default=0, ge=0)
    prompt_versions: dict[str, str] = Field(default_factory=dict)


class ObjectiveAnalysisStateResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    source_build_id: str
    pipeline_version: str
    model_name: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    stats: ExecutionStatsResponse = Field(default_factory=ExecutionStatsResponse)
    status: AnalysisStatus
    phase: str
    processed_document_count: int = 0
    total_document_count: int = 0
    current_document_id: str | None = None
    progress_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class PaperStudySourceRefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["document", "block", "table", "table_row", "figure"]
    source_ref: str


class PaperStudyDispositionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "promoted", "rejected"]
    objective_id: str | None = None
    reason: str | None = None


class PaperStudyRelationshipResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_id: str
    varied_factors: list[str] = Field(min_length=1)
    outcome: str
    source_refs: list[PaperStudySourceRefResponse] = Field(min_length=1)
    confidence: float = Field(..., ge=0, le=1)
    disposition: PaperStudyDispositionResponse


class PaperStudyInventoryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: Literal["paper_study"] = "paper_study"
    document_id: str
    doc_role: str
    study_id: str
    design_type: Literal[
        "experimental", "observational", "modeling", "mixed", "uncertain"
    ]
    claim_scope: Literal["current_work", "synthesis", "background", "uncertain"]
    experiment_label: str | None = None
    material_scope: list[str] = Field(default_factory=list)
    process_context: list[str] = Field(default_factory=list)
    sample_context: list[str] = Field(default_factory=list)
    test_context: list[str] = Field(default_factory=list)
    comparator: str | None = None
    fixed_conditions: list[str] = Field(default_factory=list)
    relationships: list[PaperStudyRelationshipResponse] = Field(min_length=1)
    confidence: float = Field(..., ge=0, le=1)


class UnresolvedPaperStudySignalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: Literal["unresolved_signal"] = "unresolved_signal"
    document_id: str
    doc_role: str
    signal_id: str
    signal_type: Literal["variable", "outcome"]
    label: str
    design_type: Literal[
        "experimental", "observational", "modeling", "mixed", "uncertain"
    ]
    claim_scope: Literal["current_work", "synthesis", "background", "uncertain"]
    experiment_label: str | None = None
    material_scope: list[str] = Field(default_factory=list)
    process_context: list[str] = Field(default_factory=list)
    sample_context: list[str] = Field(default_factory=list)
    test_context: list[str] = Field(default_factory=list)
    comparator: str | None = None
    fixed_conditions: list[str] = Field(default_factory=list)
    source_refs: list[PaperStudySourceRefResponse] = Field(min_length=1)
    confidence: float = Field(..., ge=0, le=1)
    reason: str | None = None


class PaperSourceUnitCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: Literal["source_unit_coverage"] = "source_unit_coverage"
    document_id: str
    doc_role: str
    source_unit_id: str
    window_id: str
    source_kind: Literal["document", "block", "table", "table_row", "figure"]
    source_ref: str
    status: Literal[
        "relationship_emitted",
        "unresolved_signal_emitted",
        "no_study_signal",
        "extraction_failed",
    ]
    reason: str | None = None


PaperStudyInventoryEntryResponse = Annotated[
    PaperStudyInventoryItemResponse
    | UnresolvedPaperStudySignalResponse
    | PaperSourceUnitCoverageResponse,
    Field(discriminator="item_type"),
]


class PaperStudyInventoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str
    research_objectives_ready: bool
    coverage_complete: bool
    source_unit_coverage_counts: dict[
        Literal[
            "relationship_emitted",
            "unresolved_signal_emitted",
            "no_study_signal",
            "extraction_failed",
        ],
        int,
    ]
    items: list[PaperStudyInventoryEntryResponse] = Field(default_factory=list)
    offset: int = Field(..., ge=0)
    limit: int = Field(..., ge=1)
    total: int = Field(..., ge=0)


class FindingMechanismResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_term: str
    relation_type: str
    target_term: str
    direction: EvidenceResultDirection | None = None
    assertion_strength: Literal["causal", "associative", "descriptive"]
    supporting_evidence_ids: list[str]


class FindingPaperContributionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    analysis_status: Literal["analyzed", "excluded", "failed"]
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    context_evidence_ids: list[str]
    condition_boundary_evidence_ids: list[str]


class ObjectiveEvidenceAttributeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str | int | float | bool
    unit: str | None = None


class ObjectiveEvidenceVariableResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    baseline_value: str | int | float | bool | None = None
    target_value: str | int | float | bool | None = None
    unit: str | None = None


class ObjectiveEvidenceComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_label: str
    target_label: str
    axis_names: list[str] = Field(default_factory=list)
    comparable: bool
    incomparability_reasons: list[str] = Field(default_factory=list)


class ObjectiveEvidenceResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str
    value: str | int | float | bool | None = None
    baseline_value: str | int | float | bool | None = None
    target_value: str | int | float | bool | None = None
    unit: str | None = None
    direction: EvidenceResultDirection
    result_text: str


class ObjectiveEvidenceContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: list[ObjectiveEvidenceAttributeResponse]
    sample: list[ObjectiveEvidenceAttributeResponse]
    process: list[ObjectiveEvidenceAttributeResponse]
    test: list[ObjectiveEvidenceAttributeResponse]


class FindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str
    objective_id: str
    analysis_version: int = Field(..., ge=1)
    finding_id: str
    statement: str
    factors: list[str] = Field(..., min_length=1)
    outcome: str
    direction: EvidenceResultDirection
    assertion_strength: Literal["causal", "associative", "descriptive"]
    attribution_scope: Literal[
        "isolated_effect",
        "joint_effect",
        "association_only",
        "descriptive_only",
    ]
    synthesis_status: Literal[
        "agreement",
        "conflict",
        "condition_dependent",
        "insufficient_confirmation",
    ]
    certainty: float = Field(..., ge=0, le=1)
    display_rank: int = Field(..., ge=0)
    mechanisms: list[FindingMechanismResponse]
    scientific_context: ObjectiveEvidenceContextResponse
    limitations: list[str]
    paper_contributions: list[FindingPaperContributionResponse] = Field(
        ..., min_length=1
    )


class ObjectiveEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str
    objective_id: str
    analysis_version: int
    evidence_id: str
    document_id: str
    source_kind: str
    source_ref: str
    source_excerpt: str
    page_numbers: list[int] = Field(default_factory=list)
    related_source_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_role: str
    selection_status: str
    selection_reason: str | None = None
    changed_variables: list[ObjectiveEvidenceVariableResponse] = Field(
        default_factory=list
    )
    comparison: ObjectiveEvidenceComparisonResponse | None = None
    reported_result: ObjectiveEvidenceResultResponse | None = None
    attribution_scope: EvidenceAttributionScope
    scientific_context: ObjectiveEvidenceContextResponse
    anchor_ids: list[str] = Field(default_factory=list)
    resolution_status: str
    failure_reason: str | None = None
    confidence: float


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
    evidence_disposition: Literal[
        "excluded",
        "no_routable_evidence",
        "extraction_failed",
        "no_comparable_evidence",
        "comparable_evidence",
    ] | None = None
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
    evidence_disposition: Literal[
        "excluded",
        "no_routable_evidence",
        "extraction_failed",
        "no_comparable_evidence",
        "comparable_evidence",
    ] | None = None
    routed_source_count: int | None = Field(default=None, ge=0)
    extracted_source_count: int | None = Field(default=None, ge=0)
    comparable_evidence_count: int | None = Field(default=None, ge=0)
    failed_source_count: int | None = Field(default=None, ge=0)
    evidence_disposition_reason: str | None = None


class ObjectiveAnalysisResponse(BaseModel):
    collection_id: str
    objective: ObjectiveSummaryResponse
    active_analysis: ObjectiveAnalysisStateResponse | None = None
    published_analysis: ObjectiveAnalysisStateResponse | None = None
    paper_contributions: list[PaperContributionResponse] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)


class FindingListResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    items: list[FindingResponse] = Field(default_factory=list)
    offset: int
    limit: int
    total: int


class FindingDetailResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    finding: FindingResponse


class ObjectiveEvidenceListResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str | None = None
    items: list[ObjectiveEvidenceResponse] = Field(default_factory=list)
    offset: int
    limit: int
    total: int
