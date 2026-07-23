from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ConfirmationStatus = Literal["candidate", "confirmed"]
AnalysisStatus = Literal["queued", "running", "succeeded", "failed"]


class ObjectiveSummaryResponse(BaseModel):
    collection_id: str
    objective_id: str
    question: str
    material_scope: list[str] = Field(default_factory=list)
    process_axes: list[str] = Field(default_factory=list)
    property_axes: list[str] = Field(default_factory=list)
    comparison_intent: str | None = None
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


class FindingRelationResponse(BaseModel):
    relation_order: int
    source_term: str
    relation_type: str
    target_term: str
    direction: str | None = None
    assertion_strength: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class FindingContextResponse(BaseModel):
    material_system: dict[str, Any] = Field(default_factory=dict)
    process_conditions: list[dict[str, Any]] = Field(default_factory=list)
    sample_state: dict[str, Any] = Field(default_factory=dict)
    test_conditions: list[dict[str, Any]] = Field(default_factory=list)
    comparison_baseline: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class FindingDerivationResponse(BaseModel):
    synthesis_mode: str
    comparison_status: str
    contributing_document_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str


class FindingResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    finding_level: str
    statement: str
    variables: list[str] = Field(default_factory=list)
    mediators: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    direction: str | None = None
    scope_summary: str
    evidence_strength: str
    generalization_status: str
    paper_count: int
    confidence: float
    display_rank: int
    relations: list[FindingRelationResponse] = Field(default_factory=list)
    context: FindingContextResponse
    derivation: FindingDerivationResponse


class ObjectiveEvidenceResponse(BaseModel):
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
    evidence_kind: str
    property_normalized: str | None = None
    material_system: dict[str, Any] = Field(default_factory=dict)
    sample_context: dict[str, Any] = Field(default_factory=dict)
    process_context: dict[str, Any] = Field(default_factory=dict)
    test_condition: dict[str, Any] = Field(default_factory=dict)
    resolved_condition: dict[str, Any] = Field(default_factory=dict)
    value_payload: dict[str, Any] = Field(default_factory=dict)
    unit: str | None = None
    baseline_context: dict[str, Any] = Field(default_factory=dict)
    interpretation: str | None = None
    join_keys: dict[str, Any] = Field(default_factory=dict)
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
