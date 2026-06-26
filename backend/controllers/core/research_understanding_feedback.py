from __future__ import annotations

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from application.evaluation import ResearchUnderstandingFeedbackService
from controllers.schemas.core.research_understanding import (
    ResearchUnderstandingCurationCreateRequest,
    ResearchUnderstandingCurationListResponse,
    ResearchUnderstandingCurationResponse,
    ResearchUnderstandingFeedbackCreateRequest,
    ResearchUnderstandingFeedbackListResponse,
    ResearchUnderstandingFeedbackResponse,
    ResearchUnderstandingGoldDraftResponse,
)
from domain.evaluation import ResearchUnderstandingCuration, ResearchUnderstandingFeedback

router = APIRouter(prefix="/collections", tags=["research-understanding-feedback"])
feedback_service = ResearchUnderstandingFeedbackService()


@router.post(
    "/{collection_id}/research-understanding/feedback",
    response_model=ResearchUnderstandingFeedbackResponse,
    summary="记录 research understanding claim 专家反馈",
)
async def create_research_understanding_feedback(
    collection_id: str,
    payload: ResearchUnderstandingFeedbackCreateRequest,
) -> ResearchUnderstandingFeedbackResponse:
    feedback = await run_in_threadpool(
        feedback_service.record_feedback,
        collection_id=collection_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        claim_id=payload.claim_id,
        review_status=payload.review_status,
        issue_type=payload.issue_type,
        note=payload.note,
        reviewer=payload.reviewer,
    )
    return ResearchUnderstandingFeedbackResponse(**feedback.to_record())


@router.get(
    "/{collection_id}/research-understanding/feedback",
    response_model=ResearchUnderstandingFeedbackListResponse,
    summary="读取 research understanding claim 专家反馈",
)
async def list_research_understanding_feedback(
    collection_id: str,
    scope_type: str | None = Query(default=None, max_length=32),
    scope_id: str | None = Query(default=None, max_length=160),
    claim_id: str | None = Query(default=None, max_length=200),
) -> ResearchUnderstandingFeedbackListResponse:
    items = await run_in_threadpool(
        feedback_service.list_feedback,
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
        claim_id=claim_id,
    )
    return ResearchUnderstandingFeedbackListResponse(
        collection_id=collection_id,
        items=[_feedback_response(item) for item in items],
    )


def _feedback_response(
    feedback: ResearchUnderstandingFeedback,
) -> ResearchUnderstandingFeedbackResponse:
    return ResearchUnderstandingFeedbackResponse(**feedback.to_record())


@router.post(
    "/{collection_id}/research-understanding/curations",
    response_model=ResearchUnderstandingCurationResponse,
    summary="记录 research understanding claim 专家校正",
)
async def create_research_understanding_curation(
    collection_id: str,
    payload: ResearchUnderstandingCurationCreateRequest,
) -> ResearchUnderstandingCurationResponse:
    curation = await run_in_threadpool(
        feedback_service.record_curation,
        collection_id=collection_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        claim_id=payload.claim_id,
        curated_claim_type=payload.curated_claim_type,
        curated_status=payload.curated_status,
        curated_statement=payload.curated_statement,
        curated_evidence_ref_ids=payload.curated_evidence_ref_ids,
        curated_context_ids=payload.curated_context_ids,
        note=payload.note,
        reviewer=payload.reviewer,
    )
    return _curation_response(curation)


@router.get(
    "/{collection_id}/research-understanding/curations",
    response_model=ResearchUnderstandingCurationListResponse,
    summary="读取 research understanding claim 专家校正",
)
async def list_research_understanding_curations(
    collection_id: str,
    scope_type: str | None = Query(default=None, max_length=32),
    scope_id: str | None = Query(default=None, max_length=160),
    claim_id: str | None = Query(default=None, max_length=200),
) -> ResearchUnderstandingCurationListResponse:
    items = await run_in_threadpool(
        feedback_service.list_curations,
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
        claim_id=claim_id,
    )
    return ResearchUnderstandingCurationListResponse(
        collection_id=collection_id,
        items=[_curation_response(item) for item in items],
    )


def _curation_response(
    curation: ResearchUnderstandingCuration,
) -> ResearchUnderstandingCurationResponse:
    return ResearchUnderstandingCurationResponse(**curation.to_record())


@router.get(
    "/{collection_id}/research-understanding/gold-draft",
    response_model=ResearchUnderstandingGoldDraftResponse,
    summary="导出 research understanding 专家校正 gold 草稿",
)
async def export_research_understanding_gold_draft(
    collection_id: str,
    scope_type: str = Query(..., max_length=32),
    scope_id: str = Query(..., min_length=1, max_length=160),
) -> ResearchUnderstandingGoldDraftResponse:
    draft = await run_in_threadpool(
        feedback_service.export_gold_draft,
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    return ResearchUnderstandingGoldDraftResponse(**draft)
