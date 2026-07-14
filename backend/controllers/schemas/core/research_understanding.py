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
ResearchUnderstandingDatasetLabelStatus = Literal["candidate", "silver", "gold", "rejected"]
ResearchUnderstandingDatasetUseStatus = Literal[
    "training_ready",
    "review_candidate",
    "rejected",
]
ResearchUnderstandingDatasetExportFormat = Literal[
    "json",
    "jsonl",
    "messages_jsonl",
    "review_jsonl",
]
ResearchUnderstandingFeedbackIssueType = Literal[
    "none",
    "evidence_not_grounded",
    "missing_evidence",
    "insufficient_evidence",
    "wrong_variable",
    "wrong_outcome",
    "wrong_direction",
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
    evidence_role: str | None = Field(
        default=None,
        description="Role in supporting a finding, such as direct_support or mediator_context",
    )
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
    statement: str | None = Field(default=None, description="Expert-readable relation statement")
    conditions: list[str] = Field(default_factory=list, description="Relation scope conditions")
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


class ResearchUnderstandingPresentationSummaryResponse(BaseModel):
    """Expert-readable summary for the default review workspace."""

    title: str = Field(default="Research understanding")
    material_scope: list[str] = Field(default_factory=list)
    variable_axes: list[str] = Field(default_factory=list)
    property_scope: list[str] = Field(default_factory=list)
    claim_count: int = Field(default=0)
    relation_count: int = Field(default=0)
    evidence_count: int = Field(default=0)
    context_count: int = Field(default=0)
    review_queue_count: int = Field(default=0)
    primary_finding_count: int = Field(default=0)
    review_queue_finding_count: int = Field(default=0)
    collection_document_count: int = Field(default=0)
    axis_coverage: dict[str, list[dict[str, str]]] = Field(default_factory=dict)


class ResearchUnderstandingPresentationEffectResponse(BaseModel):
    """Expert-readable effect row backed by a hidden claim binding."""

    effect_id: str
    claim_id: str
    title: str
    statement: str
    claim_type: str = Field(default="finding")
    support_status: str = Field(default="limited")
    confidence: float | None = Field(default=None)
    effect_direction: str = Field(default="")
    variable_axis: str = Field(default="")
    target_property: str = Field(default="")
    paper_count: int = Field(default=0)
    evidence_count: int = Field(default=0)
    context_summary: str = Field(default="")
    evidence_ref_ids: list[str] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    needs_review: bool = Field(default=False)
    warnings: list[str] = Field(default_factory=list)


class ResearchUnderstandingPresentationEvidenceBundleResponse(BaseModel):
    """Evidence references grouped by their role in a research finding."""

    direct_result: list[str] = Field(default_factory=list)
    mechanism: list[str] = Field(default_factory=list)
    condition_context: list[str] = Field(default_factory=list)
    background: list[str] = Field(default_factory=list)
    conflict: list[str] = Field(default_factory=list)
    noise: list[str] = Field(default_factory=list)
    uncategorized: list[str] = Field(default_factory=list)


class ResearchUnderstandingPresentationComparisonValueResponse(BaseModel):
    """One side of a traceable table or numeric comparison."""

    label: str = Field(default="")
    value: str = Field(default="")


class ResearchUnderstandingPresentationControlledConditionResponse(BaseModel):
    """Condition held fixed while comparing a variable axis."""

    axis: str = Field(default="")
    value: str = Field(default="")


class ResearchUnderstandingPresentationComparisonSummaryResponse(BaseModel):
    """Structured comparison summary for materials-expert review."""

    variable: str = Field(default="")
    direction: str = Field(default="")
    outcome: str = Field(default="")
    baseline: ResearchUnderstandingPresentationComparisonValueResponse = Field(
        default_factory=ResearchUnderstandingPresentationComparisonValueResponse
    )
    observed: ResearchUnderstandingPresentationComparisonValueResponse = Field(
        default_factory=ResearchUnderstandingPresentationComparisonValueResponse
    )
    controlled_conditions: list[
        ResearchUnderstandingPresentationControlledConditionResponse
    ] = Field(default_factory=list)


class ResearchUnderstandingPresentationFindingResponse(BaseModel):
    """Expert-facing research finding row for materials review."""

    finding_id: str
    claim_id: str
    title: str
    statement: str
    variables: list[str] = Field(default_factory=list)
    mediators: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    direction: str = Field(default="")
    scope_summary: str = Field(default="")
    support_grade: str = Field(default="weak")
    review_status: str = Field(default="pending_review")
    confidence: float | None = Field(default=None)
    paper_count: int = Field(default=0)
    evidence_count: int = Field(default=0)
    evidence_ref_ids: list[str] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    evidence_bundle: ResearchUnderstandingPresentationEvidenceBundleResponse = Field(
        default_factory=ResearchUnderstandingPresentationEvidenceBundleResponse
    )
    comparison_summary: ResearchUnderstandingPresentationComparisonSummaryResponse | None = (
        Field(default=None)
    )
    expert_use_status: str = Field(default="review_candidate")
    dataset_use_status: str = Field(default="review_candidate")
    generalization_status: str = Field(default="cross_paper_candidate")
    generalization_note: str = Field(default="")
    evidence_gap_summary: str = Field(default="")
    upgrade_actions: list[str] = Field(default_factory=list)
    related_review_finding_ids: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResearchUnderstandingPresentationEvidenceResponse(BaseModel):
    """Expert-readable evidence card used by the presentation workspace."""

    evidence_ref_id: str
    document_id: str | None = Field(default=None)
    title: str
    source_label: str
    source_kind: str = Field(default="unknown")
    source_ref: str | None = Field(default=None)
    block_type: str | None = Field(default=None)
    heading_path: str | None = Field(default=None)
    page: str | None = Field(default=None)
    quote: str | None = Field(default=None)
    source_text: str | None = Field(default=None)
    value_summary: str = Field(default="")
    table_audit: dict[str, Any] | None = Field(default=None)
    traceability_status: str = Field(default="unknown")
    evidence_role: str | None = Field(default=None)
    confidence: float | None = Field(default=None)
    href: str | None = Field(default=None)


class ResearchUnderstandingPresentationContextResponse(BaseModel):
    """Expert-readable condition summary for a claim or effect."""

    context_id: str
    label: str
    material_scope: list[str] = Field(default_factory=list)
    property_scope: list[str] = Field(default_factory=list)
    process_summary: str = Field(default="")
    test_summary: str = Field(default="")
    limitations: list[str] = Field(default_factory=list)


class ResearchUnderstandingPresentationResponse(BaseModel):
    """Default presentation projection for materials-expert review."""

    summary: ResearchUnderstandingPresentationSummaryResponse = Field(
        default_factory=ResearchUnderstandingPresentationSummaryResponse
    )
    effects: list[ResearchUnderstandingPresentationEffectResponse] = Field(
        default_factory=list
    )
    findings: list[ResearchUnderstandingPresentationFindingResponse] = Field(
        default_factory=list
    )
    primary_findings: list[ResearchUnderstandingPresentationFindingResponse] = Field(
        default_factory=list
    )
    review_queue_findings: list[ResearchUnderstandingPresentationFindingResponse] = Field(
        default_factory=list
    )
    evidence_items: list[ResearchUnderstandingPresentationEvidenceResponse] = Field(
        default_factory=list
    )
    context_summaries: list[ResearchUnderstandingPresentationContextResponse] = Field(
        default_factory=list
    )


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
    presentation: ResearchUnderstandingPresentationResponse = Field(
        default_factory=ResearchUnderstandingPresentationResponse,
        description="Expert-readable presentation projection for the default UI",
    )


class ResearchUnderstandingFeedbackCreateRequest(BaseModel):
    """Expert feedback captured on one research-understanding finding."""

    model_config = ConfigDict(extra="ignore")

    scope_type: UnderstandingScopeType
    scope_id: str = Field(..., min_length=1, max_length=160)
    finding_id: str = Field(..., min_length=1, max_length=200)
    claim_id: str | None = Field(default=None, max_length=200)
    review_status: ResearchUnderstandingFeedbackStatus
    issue_type: ResearchUnderstandingFeedbackIssueType = Field(default="none")
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)


class ResearchUnderstandingFeedbackResponse(BaseModel):
    """Persisted expert feedback on one finding."""

    feedback_id: str
    collection_id: str
    scope_type: str
    scope_id: str
    finding_id: str
    claim_id: str | None = None
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
    """Expert-curated correction for one research-understanding finding."""

    model_config = ConfigDict(extra="ignore")

    scope_type: UnderstandingScopeType
    scope_id: str = Field(..., min_length=1, max_length=160)
    finding_id: str = Field(..., min_length=1, max_length=200)
    claim_id: str | None = Field(default=None, max_length=200)
    curated_claim_type: ClaimType = Field(default="finding")
    curated_status: ClaimStatus = Field(default="limited")
    curated_statement: str = Field(..., min_length=1, max_length=4000)
    curated_support_grade: str | None = Field(default=None, max_length=40)
    curated_review_status: str | None = Field(default=None, max_length=40)
    curated_variables: list[str] = Field(default_factory=list, max_length=40)
    curated_mediators: list[str] = Field(default_factory=list, max_length=40)
    curated_outcomes: list[str] = Field(default_factory=list, max_length=40)
    curated_direction: str | None = Field(default=None, max_length=80)
    curated_scope_summary: str | None = Field(default=None, max_length=1000)
    curated_evidence_ref_ids: list[str] = Field(default_factory=list, max_length=80)
    curated_context_ids: list[str] = Field(default_factory=list, max_length=80)
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)


class ResearchUnderstandingCurationResponse(BaseModel):
    """Persisted expert-curated finding correction."""

    curation_id: str
    collection_id: str
    scope_type: str
    scope_id: str
    finding_id: str
    claim_id: str | None = None
    curated_claim_type: ClaimType
    curated_status: ClaimStatus
    curated_statement: str
    curated_support_grade: str | None = None
    curated_review_status: str | None = None
    curated_variables: list[str] = Field(default_factory=list)
    curated_mediators: list[str] = Field(default_factory=list)
    curated_outcomes: list[str] = Field(default_factory=list)
    curated_direction: str | None = None
    curated_scope_summary: str | None = None
    curated_evidence_ref_ids: list[str] = Field(default_factory=list)
    curated_context_ids: list[str] = Field(default_factory=list)
    note: str | None = None
    reviewer: str | None = None
    updated_at: str


class ResearchUnderstandingCurationListResponse(BaseModel):
    """Collection-bound research-understanding claim curation list."""

    collection_id: str
    items: list[ResearchUnderstandingCurationResponse] = Field(default_factory=list)


class ResearchUnderstandingGoldDraftItemResponse(BaseModel):
    """Gold-item draft derived from expert-curated research-understanding claims."""

    gold_item_id: str
    document_id: str
    family: str
    item_key: str
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchUnderstandingGoldDraftResponse(BaseModel):
    """Read-only gold-set draft exported from expert claim curations."""

    collection_id: str
    scope_type: str
    scope_id: str
    gold_id: str
    target_layer: str
    metric_profile: str
    item_count: int
    items: list[ResearchUnderstandingGoldDraftItemResponse] = Field(default_factory=list)


class ResearchUnderstandingDatasetQualitySummaryResponse(BaseModel):
    """Scope-level quality summary derived from exported dataset samples."""

    total_samples: int = Field(default=0)
    usable_sample_count: int = Field(default=0)
    training_ready_sample_count: int = Field(default=0)
    training_message_sample_count: int = Field(default=0)
    review_candidate_sample_count: int = Field(default=0)
    next_review_finding_id: str = Field(default="")
    needs_review_count: int = Field(default=0)
    rejected_count: int = Field(default=0)
    labeled_sample_count: int = Field(default=0)
    accepted_system_sample_count: int = Field(default=0)
    accepted_after_curation_match_count: int = Field(default=0)
    curated_correction_count: int = Field(default=0)
    system_error_count: int = Field(default=0)
    resolved_feedback_count: int = Field(default=0)
    by_label_status: dict[str, int] = Field(default_factory=dict)
    by_dataset_use_status: dict[str, int] = Field(default_factory=dict)
    by_review_status: dict[str, int] = Field(default_factory=dict)
    by_issue_type: dict[str, int] = Field(default_factory=dict)
    by_error_category: dict[str, int] = Field(default_factory=dict)
    by_support_grade: dict[str, int] = Field(default_factory=dict)
    by_trace_status: dict[str, int] = Field(default_factory=dict)
    by_evidence_role: dict[str, int] = Field(default_factory=dict)
    by_evidence_traceability_status: dict[str, int] = Field(default_factory=dict)
    by_quality_decision: dict[str, int] = Field(default_factory=dict)
    by_presentation_bucket: dict[str, int] = Field(default_factory=dict)
    by_bucket_quality_decision: dict[str, dict[str, int]] = Field(default_factory=dict)
    top_error_categories: list[dict[str, Any]] = Field(default_factory=list)
    top_issue_types: list[dict[str, Any]] = Field(default_factory=list)
    top_review_reasons: list[dict[str, Any]] = Field(default_factory=list)
    top_system_warnings: list[dict[str, Any]] = Field(default_factory=list)
    warning_counts: dict[str, int] = Field(default_factory=dict)


class ResearchUnderstandingDatasetSampleResponse(BaseModel):
    """Dataset sample derived from one research-understanding finding."""

    sample_id: str
    task_type: str
    collection_id: str
    scope_type: str
    scope_id: str
    finding_id: str
    claim_id: str | None = None
    label_status: ResearchUnderstandingDatasetLabelStatus
    dataset_use_status: ResearchUnderstandingDatasetUseStatus = Field(
        default="review_candidate"
    )
    presentation_bucket: str = Field(default="unbucketed")
    trace_status: str = Field(default="unavailable")
    input_blocks: list[dict[str, Any]] = Field(default_factory=list)
    prompt_version: str | None = None
    model_output: dict[str, Any] | None = None
    system_prediction: dict[str, Any] = Field(default_factory=dict)
    review_action: dict[str, str] = Field(default_factory=dict)
    expert_target: dict[str, Any] | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    training_evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    training_messages: list[dict[str, Any]] = Field(default_factory=list)
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    feedback_refs: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchUnderstandingDatasetResponse(BaseModel):
    """Read-only dataset export for evaluation and fine-tuning preparation."""

    schema_version: str
    dataset_id: str
    collection_id: str
    scope_type: str
    scope_id: str
    task_type: str
    metric_profile: str
    label_status_filter: ResearchUnderstandingDatasetLabelStatus | None = None
    dataset_use_status_filter: ResearchUnderstandingDatasetUseStatus | None = None
    item_count: int
    label_counts: dict[str, int] = Field(default_factory=dict)
    quality_summary: ResearchUnderstandingDatasetQualitySummaryResponse = Field(
        default_factory=ResearchUnderstandingDatasetQualitySummaryResponse
    )
    items: list[ResearchUnderstandingDatasetSampleResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
