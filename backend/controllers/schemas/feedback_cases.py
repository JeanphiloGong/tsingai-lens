"""HTTP schemas for the feedback workbench read surface."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedbackCaseSummaryResponse(BaseModel):
    case_id: str
    collection_id: str
    status: str
    anchor_message_id: str
    problem_type: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    needs_human_review: bool
    created_at: str
    question_preview: str = ""
    answer_preview: str = ""
    document_titles: list[str] = Field(default_factory=list)
    coverage_status: str = "unknown"


class FeedbackCaseListResponse(BaseModel):
    items: list[FeedbackCaseSummaryResponse]
    limit: int
    offset: int


class FeedbackCaseDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: str
    collection_id: str
    session_id: str
    status: str
    source_signals: list[dict[str, Any]] = Field(default_factory=list)
    question: str
    answer: str
    requested_scope: list[dict[str, Any]] = Field(default_factory=list)
    inspected_sources: list[dict[str, Any]] = Field(default_factory=list)
    omitted_candidates: list[dict[str, Any]] = Field(default_factory=list)
    claim_support: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    coverage_status: str = "unknown"
    analysis: dict[str, Any] | None = None
    annotation: dict[str, Any] | None = None
    current_annotation_digest: str | None = None
    technical_error: str | None = None
    created_at: str
    updated_at: str


class FeedbackAnnotationRequest(BaseModel):
    expected_digest: str | None = Field(default=None, min_length=64, max_length=64)
    problem_type: Literal[
        "fact_error",
        "source_missing",
        "evidence_mismatch",
        "retrieval_failure",
        "tool_failure",
        "intent_mismatch",
        "incomplete_answer",
        "style_or_format",
        "undetermined_dissatisfaction",
    ]
    severity: Literal["low", "medium", "high", "critical"]
    target: str | None = Field(default=None, max_length=20000)
    support_source_refs: list[str] = Field(default_factory=list, max_length=100)
    dataset_uses: list[Literal["evaluation", "sft", "preference"]] = Field(
        default_factory=list, max_length=3
    )
    reason: str = Field(min_length=1, max_length=4000)


class FeedbackAnnotationResponse(BaseModel):
    annotation_id: str
    case_id: str
    version: int
    problem_type: str
    severity: str
    target: str | None
    support_source_refs: list[str]
    dataset_uses: list[str]
    reason: str
    annotation_digest: str
    created_by: str
    created_at: str
    updated_at: str
