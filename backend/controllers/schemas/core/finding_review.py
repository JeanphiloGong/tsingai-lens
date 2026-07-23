from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FindingReviewStatus = Literal["correct", "incorrect", "partial", "unclear"]
FindingIssueType = Literal[
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
FindingStatus = Literal["supported", "limited", "conflicted", "unsupported"]
FindingDatasetLabelStatus = Literal["candidate", "silver", "gold", "rejected"]
FindingDatasetUseStatus = Literal["training_ready", "review_candidate", "rejected"]


class FindingFeedbackCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_version: int = Field(..., ge=1)
    review_status: FindingReviewStatus
    issue_type: FindingIssueType = Field(default="none")
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)


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
    curated_statement: str = Field(..., min_length=1, max_length=4000)
    curated_support_grade: str | None = Field(default=None, max_length=40)
    curated_review_status: str | None = Field(default=None, max_length=40)
    curated_variables: list[str] = Field(default_factory=list, max_length=40)
    curated_mediators: list[str] = Field(default_factory=list, max_length=40)
    curated_outcomes: list[str] = Field(default_factory=list, max_length=40)
    curated_direction: str | None = Field(default=None, max_length=80)
    curated_scope_summary: str | None = Field(default=None, max_length=1000)
    curated_evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)


class FindingCurationResponse(BaseModel):
    curation_id: str
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    curated_status: FindingStatus
    curated_statement: str
    curated_support_grade: str | None = None
    curated_review_status: str | None = None
    curated_variables: list[str] = Field(default_factory=list)
    curated_mediators: list[str] = Field(default_factory=list)
    curated_outcomes: list[str] = Field(default_factory=list)
    curated_direction: str | None = None
    curated_scope_summary: str | None = None
    curated_evidence_ids: list[str] = Field(default_factory=list)
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
    finding_level: str
    document_ids: list[str] = Field(default_factory=list)
    label_status: FindingDatasetLabelStatus
    dataset_use_status: FindingDatasetUseStatus
    system_prediction: dict[str, Any] = Field(default_factory=dict)
    expert_target: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
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
