from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controllers.schemas.core.research_objectives import (
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
