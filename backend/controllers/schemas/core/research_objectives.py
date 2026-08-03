from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ConfirmationStatus = Literal["candidate", "confirmed"]
AnalysisStatus = Literal["queued", "running", "succeeded", "failed"]
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
    confirmation_status: ConfirmationStatus
    active_analysis_version: int | None = None
    published_analysis_version: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ObjectiveAnalysisStateResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    source_build_id: str
    pipeline_version: str
    model_name: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
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


class ObjectiveListResponse(BaseModel):
    collection_id: str
    objectives: list[ObjectiveSummaryResponse] = Field(default_factory=list)


class ObjectiveAnalysisResponse(BaseModel):
    collection_id: str
    objective: ObjectiveSummaryResponse
    active_analysis: ObjectiveAnalysisStateResponse | None = None
    published_analysis: ObjectiveAnalysisStateResponse | None = None
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
