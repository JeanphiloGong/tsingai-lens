from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controllers.schemas.core.research_objectives import (
    EvidenceContextScope,
    FindingResponse,
    ObjectiveAnalysisStateResponse,
    ObjectiveEvidenceResponse,
)


FindingReviewStatus = Literal["correct", "incorrect", "partial", "unclear"]
FindingIssueType = Literal[
    "none",
    "evidence_not_grounded",
    "missing_evidence",
    "insufficient_evidence",
    "wrong_factor",
    "wrong_outcome",
    "wrong_direction",
    "wrong_context",
    "wrong_mechanism",
    "wrong_attribution",
    "wrong_synthesis",
    "overclaim",
    "unclear_statement",
    "other",
]
FindingStatus = Literal["supported", "limited", "conflicted", "unsupported"]
FindingDatasetLabelStatus = Literal["candidate", "silver", "gold", "rejected"]
FindingDatasetUseStatus = Literal["training_ready", "review_candidate", "rejected"]
FindingAssertionStrength = Literal["causal", "associative", "descriptive"]
FindingAbstentionReason = Literal[
    "no_comparable_evidence",
    "no_grounded_evidence",
    "insufficient_evidence",
]
EvidenceSourceKind = Literal["text_window", "table", "figure"]
EvidenceRole = Literal[
    "direct_result",
    "condition_context",
    "mechanism_context",
    "baseline_context",
    "comparison_context",
    "background_context",
    "contradictory_result",
    "irrelevant",
]
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
ScientificScalar = str | int | float | bool


class EvidenceVariableCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=240)
    baseline_value: ScientificScalar | None = None
    target_value: ScientificScalar | None = None
    unit: str | None = Field(default=None, max_length=80)


class EvidenceComparisonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_label: str = Field(..., min_length=1, max_length=500)
    target_label: str = Field(..., min_length=1, max_length=500)
    axis_names: list[str] = Field(default_factory=list, max_length=20)
    comparable: bool
    incomparability_reasons: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_text_lengths(self) -> "EvidenceComparisonCreate":
        if any(not value.strip() or len(value) > 240 for value in self.axis_names):
            raise ValueError("comparison axes must be non-empty and at most 240 characters")
        if any(len(value) > 1000 for value in self.incomparability_reasons):
            raise ValueError("incomparability reasons cannot exceed 1000 characters")
        return self


class EvidenceResultCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(..., min_length=1, max_length=500)
    value: ScientificScalar | None = None
    baseline_value: ScientificScalar | None = None
    target_value: ScientificScalar | None = None
    unit: str | None = Field(default=None, max_length=80)
    direction: EvidenceResultDirection
    result_text: str = Field(..., min_length=1, max_length=5000)


class EvidenceAttributeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=240)
    value: ScientificScalar
    unit: str | None = Field(default=None, max_length=80)
    context_scope: EvidenceContextScope = "unknown"


class EvidenceContextCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: list[EvidenceAttributeCreate] = Field(default_factory=list, max_length=40)
    sample: list[EvidenceAttributeCreate] = Field(default_factory=list, max_length=40)
    process: list[EvidenceAttributeCreate] = Field(default_factory=list, max_length=40)
    test: list[EvidenceAttributeCreate] = Field(default_factory=list, max_length=40)


class EvidenceAuthoringCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_analysis_version: int = Field(..., ge=1)
    document_id: str = Field(..., min_length=1, max_length=240)
    source_kind: EvidenceSourceKind
    source_ref: str = Field(..., min_length=1, max_length=240)
    source_excerpt: str = Field(..., min_length=1, max_length=20_000)
    evidence_role: EvidenceRole
    changed_variables: list[EvidenceVariableCreate] = Field(
        default_factory=list, max_length=20
    )
    comparison: EvidenceComparisonCreate | None = None
    reported_result: EvidenceResultCreate | None = None
    attribution_scope: EvidenceAttributionScope
    scientific_context: EvidenceContextCreate = Field(
        default_factory=EvidenceContextCreate
    )
    supersedes_evidence_id: str | None = Field(default=None, max_length=128)
    authoring_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_scientific_shape(self) -> "EvidenceAuthoringCreateRequest":
        result_role = self.evidence_role in {
            "direct_result",
            "contradictory_result",
        }
        if result_role and self.reported_result is None:
            raise ValueError("result Evidence requires a reported result")
        if not result_role and self.reported_result is not None:
            raise ValueError("context Evidence cannot contain a reported result")
        if self.attribution_scope in {"isolated_effect", "joint_effect"}:
            if self.comparison is None or not self.comparison.comparable:
                raise ValueError("experimental attribution requires a comparison")
            if not self.changed_variables:
                raise ValueError("experimental attribution requires changed variables")
        return self


class EvidenceAuthoringResponse(BaseModel):
    analysis: ObjectiveAnalysisStateResponse
    evidence: ObjectiveEvidenceResponse


class FindingAuthoringCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_analysis_version: int = Field(..., ge=1)
    statement: str | None = Field(default=None, max_length=3000)
    assertion_strength: FindingAssertionStrength | None = None
    supporting_evidence_ids: list[str] = Field(
        default_factory=list, max_length=100
    )
    contradicting_evidence_ids: list[str] = Field(
        default_factory=list, max_length=100
    )
    context_evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    condition_boundary_evidence_ids: list[str] = Field(
        default_factory=list, max_length=100
    )
    limitations: list[str] = Field(default_factory=list, max_length=20)
    parent_finding_id: str | None = Field(default=None, max_length=128)
    abstention_reason: FindingAbstentionReason | None = None

    @model_validator(mode="after")
    def validate_authoring_mode(self) -> "FindingAuthoringCreateRequest":
        if any(len(value.strip()) > 1000 for value in self.limitations):
            raise ValueError("Finding limitations cannot exceed 1000 characters")
        selected = (
            self.supporting_evidence_ids
            + self.contradicting_evidence_ids
            + self.context_evidence_ids
            + self.condition_boundary_evidence_ids
        )
        if any(not value.strip() or len(value) > 128 for value in selected):
            raise ValueError("Evidence IDs must be non-empty and at most 128 characters")
        if self.abstention_reason is not None:
            if (
                (self.statement or "").strip()
                or self.assertion_strength is not None
                or selected
                or self.parent_finding_id is not None
            ):
                raise ValueError(
                    "abstention cannot contain a Finding statement or Evidence roles"
                )
            if not any(value.strip() for value in self.limitations):
                raise ValueError("abstention requires an explanation")
            return self
        if not (self.statement or "").strip():
            raise ValueError("Finding statement is required")
        if self.assertion_strength is None:
            raise ValueError("Finding assertion strength is required")
        if not self.supporting_evidence_ids:
            raise ValueError("Finding requires supporting Evidence")
        return self


class FindingAuthoringResponse(BaseModel):
    analysis: ObjectiveAnalysisStateResponse
    finding: FindingResponse | None = None
    abstention_reason: FindingAbstentionReason | None = None


class FindingFeedbackCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_version: int = Field(..., ge=1)
    review_status: FindingReviewStatus
    issue_type: FindingIssueType = Field(default="none")
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_decision(self) -> "FindingFeedbackCreateRequest":
        if self.review_status == "correct" and self.issue_type != "none":
            raise ValueError("correct feedback cannot report an issue")
        if self.review_status in {"incorrect", "partial"} and self.issue_type == "none":
            raise ValueError(f"{self.review_status} feedback requires an issue")
        return self


class FindingFeedbackResponse(BaseModel):
    feedback_id: str
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    review_status: FindingReviewStatus
    issue_type: FindingIssueType
    note: str | None = None
    reviewer: str | None = None
    created_at: str


class FindingFeedbackListResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    items: list[FindingFeedbackResponse] = Field(default_factory=list)


class FindingCurationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_version: int = Field(..., ge=1)
    curated_status: FindingStatus = Field(default="limited")
    curated_finding: FindingResponse
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)


class FindingCurationResponse(BaseModel):
    curation_id: str
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    curated_status: FindingStatus
    curated_finding: FindingResponse
    note: str | None = None
    reviewer: str | None = None
    updated_at: str


class FindingCurationListResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    items: list[FindingCurationResponse] = Field(default_factory=list)


class FindingDatasetSampleResponse(BaseModel):
    sample_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    research_objective: str
    document_ids: list[str] = Field(default_factory=list)
    label_status: FindingDatasetLabelStatus
    dataset_use_status: FindingDatasetUseStatus
    finding_fingerprint: str
    evidence_fingerprint: str
    system_prediction: FindingResponse
    expert_target: FindingResponse | None = None
    training_target: FindingResponse
    evidence: list[ObjectiveEvidenceResponse] = Field(default_factory=list)
    training_schema_version: str
    training_prompt_version: str
    training_messages: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FindingDatasetResponse(BaseModel):
    schema_version: str
    collection_id: str
    objective_id: str | None = None
    items: list[FindingDatasetSampleResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FindingGoldDraftResponse(BaseModel):
    gold_id: str
    collection_id: str
    version: str
    target_layer: str
    metric_profile: str
    items: list[dict[str, Any]] = Field(default_factory=list)
