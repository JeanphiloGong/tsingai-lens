"""Authenticated feedback workbench read endpoints."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from application.feedback import feedback_case_service
from controllers.dependencies.auth import get_current_user_id
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from utils.response import ApiResponse, make_api_response


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
    review_decisions: list[dict[str, Any]] = Field(default_factory=list)
    technical_error: str | None = None
    created_at: str
    updated_at: str


class FeedbackAnnotationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

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

    @field_validator("target")
    @classmethod
    def empty_target_is_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("support_source_refs", "dataset_uses")
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))


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


class FeedbackReviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expected_annotation_digest: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    decision: Literal["accept", "reject", "insufficient", "withdraw"]
    reason: str = Field(min_length=1, max_length=4000)


class FeedbackReviewDecisionResponse(BaseModel):
    decision_id: str
    case_id: str
    annotation_digest: str
    decision: str
    reason: str | None
    created_by: str
    seq: int
    created_at: str


class FeedbackReviewDecisionListResponse(BaseModel):
    items: list[FeedbackReviewDecisionResponse]


feedback_case_router = APIRouter(prefix="/feedback-cases", tags=["feedback-workbench"])


@feedback_case_router.get("", response_model=ApiResponse[FeedbackCaseListResponse])
async def list_feedback_cases(
    user_id: Annotated[str, Depends(get_current_user_id)],
    collection_id: str | None = Query(default=None, min_length=1, max_length=64),
    status: str | None = Query(default=None, min_length=1, max_length=32),
    problem_type: str | None = Query(default=None, min_length=1, max_length=64),
    needs_human_review: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Response:
    items = await feedback_case_service.list_feedback_cases_for_user(
        user_id=user_id,
        collection_id=collection_id,
        status=status,
        problem_type=problem_type,
        needs_human_review=needs_human_review,
        limit=limit,
        offset=offset,
    )
    return make_api_response(
        data=FeedbackCaseListResponse(
            items=[
                FeedbackCaseSummaryResponse.model_validate(item, from_attributes=True)
                for item in items
            ],
            limit=limit,
            offset=offset,
        )
    )


@feedback_case_router.get(
    "/{case_id}", response_model=ApiResponse[FeedbackCaseDetailResponse]
)
async def get_feedback_case(
    case_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    detail = await feedback_case_service.get_feedback_case_for_user(case_id, user_id)
    return make_api_response(data=FeedbackCaseDetailResponse.model_validate(detail))


@feedback_case_router.patch(
    "/{case_id}/annotation", response_model=ApiResponse[FeedbackAnnotationResponse]
)
async def save_feedback_annotation(
    case_id: str,
    payload: FeedbackAnnotationRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    annotation = await feedback_case_service.save_feedback_annotation_for_user(
        case_id=case_id,
        user_id=user_id,
        expected_digest=payload.expected_digest,
        problem_type=payload.problem_type,
        severity=payload.severity,
        target=payload.target,
        support_source_refs=tuple(payload.support_source_refs),
        dataset_uses=tuple(payload.dataset_uses),
        reason=payload.reason,
    )
    return make_api_response(
        data=FeedbackAnnotationResponse.model_validate(annotation, from_attributes=True)
    )


@feedback_case_router.post(
    "/{case_id}/review", response_model=ApiResponse[FeedbackReviewDecisionResponse]
)
async def submit_feedback_review(
    case_id: str,
    payload: FeedbackReviewRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=128
    ),
) -> Response:
    decision = await feedback_case_service.submit_feedback_review_for_user(
        case_id=case_id,
        user_id=user_id,
        expected_annotation_digest=payload.expected_annotation_digest,
        decision=payload.decision,
        reason=payload.reason,
        idempotency_key=idempotency_key,
    )
    return make_api_response(
        data=FeedbackReviewDecisionResponse.model_validate(
            decision, from_attributes=True
        )
    )


@feedback_case_router.get(
    "/{case_id}/review-decisions",
    response_model=ApiResponse[FeedbackReviewDecisionListResponse],
)
async def list_feedback_reviews(
    case_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    decisions = await feedback_case_service.list_feedback_reviews_for_user(
        case_id=case_id,
        user_id=user_id,
    )
    return make_api_response(
        data=FeedbackReviewDecisionListResponse(
            items=[
                FeedbackReviewDecisionResponse.model_validate(
                    item, from_attributes=True
                )
                for item in decisions
            ]
        )
    )


__all__ = ["feedback_case_router"]
