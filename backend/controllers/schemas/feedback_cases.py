"""HTTP schemas for the feedback workbench read surface."""

from __future__ import annotations

from typing import Any

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
