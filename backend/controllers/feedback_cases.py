"""Authenticated feedback workbench read endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request

from application.feedback.feedback_case_service import FeedbackCaseService
from controllers.dependencies.auth import current_user_id
from controllers.schemas.feedback_cases import (
    FeedbackAnnotationRequest,
    FeedbackAnnotationResponse,
    FeedbackCaseDetailResponse,
    FeedbackCaseListResponse,
    FeedbackCaseSummaryResponse,
    FeedbackReviewDecisionListResponse,
    FeedbackReviewDecisionResponse,
    FeedbackReviewRequest,
)


router = APIRouter(prefix="/feedback-cases", tags=["feedback-workbench"])


def _service(request: Request) -> FeedbackCaseService:
    service = getattr(request.app.state, "feedback_case_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "feedback_workbench_unavailable",
                "message": "feedback workbench is not configured",
            },
        )
    return service


@router.get("", response_model=FeedbackCaseListResponse)
async def list_feedback_cases(
    request: Request,
    collection_id: str | None = Query(default=None, min_length=1, max_length=64),
    status: str | None = Query(default=None, min_length=1, max_length=32),
    problem_type: str | None = Query(default=None, min_length=1, max_length=64),
    needs_human_review: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FeedbackCaseListResponse:
    try:
        items = await _service(request).list_for_user(
            user_id=await current_user_id(request),
            collection_id=collection_id,
            status=status,
            problem_type=problem_type,
            needs_human_review=needs_human_review,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "feedback_case_filter_invalid", "message": str(exc)},
        ) from exc
    return FeedbackCaseListResponse(
        items=[FeedbackCaseSummaryResponse.model_validate(item.__dict__) for item in items],
        limit=limit,
        offset=offset,
    )


@router.get("/{case_id}", response_model=FeedbackCaseDetailResponse)
async def get_feedback_case(
    case_id: str,
    request: Request,
) -> FeedbackCaseDetailResponse:
    try:
        detail = await _service(request).read_for_user(
            case_id, await current_user_id(request)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FeedbackCaseDetailResponse.model_validate(detail)


@router.patch("/{case_id}/annotation", response_model=FeedbackAnnotationResponse)
async def save_feedback_annotation(
    case_id: str,
    payload: FeedbackAnnotationRequest,
    request: Request,
) -> FeedbackAnnotationResponse:
    try:
        annotation = await _service(request).save_annotation_for_user(
            case_id=case_id,
            user_id=await current_user_id(request),
            expected_digest=payload.expected_digest,
            problem_type=payload.problem_type,
            severity=payload.severity,
            target=payload.target,
            support_source_refs=tuple(payload.support_source_refs),
            dataset_uses=tuple(payload.dataset_uses),
            reason=payload.reason,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        code = str(exc)
        status = 409 if code in {"feedback_case_stale", "annotation_version_conflict"} else 422
        raise HTTPException(
            status_code=status,
            detail={"code": code, "message": code.replace("_", " ")},
        ) from exc
    return FeedbackAnnotationResponse.model_validate(annotation.to_record())


@router.post("/{case_id}/review", response_model=FeedbackReviewDecisionResponse)
async def submit_feedback_review(
    case_id: str,
    payload: FeedbackReviewRequest,
    request: Request,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=128
    ),
) -> FeedbackReviewDecisionResponse:
    try:
        decision = await _service(request).submit_review_for_user(
            case_id=case_id,
            user_id=await current_user_id(request),
            expected_annotation_digest=payload.expected_annotation_digest,
            decision=payload.decision,
            reason=payload.reason,
            idempotency_key=idempotency_key,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        code = str(exc)
        status = 409 if code in {
            "feedback_case_stale",
            "feedback_case_not_reviewable",
            "feedback_case_not_withdrawable",
            "idempotency_key_invalid",
        } else 422
        raise HTTPException(
            status_code=status,
            detail={"code": code, "message": code.replace("_", " ")},
        ) from exc
    return FeedbackReviewDecisionResponse.model_validate(decision.to_record())


@router.get(
    "/{case_id}/review-decisions",
    response_model=FeedbackReviewDecisionListResponse,
)
async def list_feedback_reviews(
    case_id: str,
    request: Request,
) -> FeedbackReviewDecisionListResponse:
    try:
        decisions = await _service(request).list_reviews_for_user(
            case_id=case_id,
            user_id=await current_user_id(request),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FeedbackReviewDecisionListResponse(
        items=[FeedbackReviewDecisionResponse.model_validate(item.to_record()) for item in decisions]
    )


__all__ = ["router"]
