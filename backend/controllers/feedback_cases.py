"""Authenticated feedback workbench read endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from application.feedback.feedback_case_service import FeedbackCaseService
from controllers.dependencies.auth import current_user_id
from controllers.schemas.feedback_cases import (
    FeedbackCaseDetailResponse,
    FeedbackCaseListResponse,
    FeedbackCaseSummaryResponse,
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


__all__ = ["router"]
