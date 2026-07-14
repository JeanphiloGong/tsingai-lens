from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from application.evaluation import ResearchUnderstandingFeedbackService
from controllers.dependencies.auth import require_current_user
from controllers.schemas.core.research_understanding import (
    ResearchUnderstandingCurationCreateRequest,
    ResearchUnderstandingCurationListResponse,
    ResearchUnderstandingCurationResponse,
    ResearchUnderstandingFeedbackCreateRequest,
    ResearchUnderstandingFeedbackListResponse,
    ResearchUnderstandingFeedbackResponse,
    ResearchUnderstandingDatasetExportFormat,
    ResearchUnderstandingDatasetLabelStatus,
    ResearchUnderstandingDatasetResponse,
    ResearchUnderstandingDatasetUseStatus,
    ResearchUnderstandingGoldDraftResponse,
)
from domain.evaluation import ResearchUnderstandingCuration, ResearchUnderstandingFeedback

router = APIRouter(prefix="/collections", tags=["research-understanding-feedback"])
feedback_service = ResearchUnderstandingFeedbackService()
REVIEW_ACTION_OPTIONS = ("accept", "reject", "correct", "skip")
REJECT_ISSUE_OPTIONS = (
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
)
REVIEW_INSTRUCTIONS = (
    "Set action=accept only after the finding, direction, scope, and cited "
    "evidence match. Set action=reject with issue_type when the evidence does "
    "not support the finding. Set action=correct with suggested_target when "
    "the finding is partly right. Leave action=skip for unchecked rows."
)
REVIEW_RISK_FLAGS = {
    "accept_as_paper_level": "Paper-level evidence; do not treat as cross-paper conclusion without confirmation.",
    "review_table_rows": "Table-row finding; verify selected rows and changed variables before accepting.",
    "verify_table_rows": "Parsed table alignment is uncertain; verify source table before accepting.",
    "review_table_variables": "Multiple table variables may change together; avoid assigning a single-variable effect without checking.",
    "check_mechanism_requirement": "Mechanism evidence may be missing; decide whether the final label needs mechanism support.",
    "resolve_conflict": "Conflicting direction; resolve evidence conflict before downstream use.",
}


def _dataset_jsonl_response(
    response: ResearchUnderstandingDatasetResponse,
    *,
    messages_only: bool = False,
) -> Response:
    rows: list[dict[str, Any]]
    if messages_only:
        rows = [
            {"messages": item.training_messages}
            for item in response.items
            if item.training_messages
        ]
    else:
        rows = [item.model_dump(mode="json") for item in response.items]
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if body:
        body += "\n"
    return Response(content=body, media_type="application/x-ndjson")


def _dataset_review_jsonl_response(
    response: ResearchUnderstandingDatasetResponse,
) -> Response:
    rows = [
        _review_jsonl_row(response.collection_id, item)
        for item in response.items
        if item.dataset_use_status == "review_candidate"
    ]
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if body:
        body += "\n"
    return Response(content=body, media_type="application/x-ndjson")


def _review_jsonl_row(
    collection_id: str,
    item: Any,
) -> dict[str, Any]:
    prediction = item.system_prediction or {}
    expert_target = item.expert_target or {}
    evidence = item.training_evidence_refs or item.evidence_refs or item.input_blocks
    review_action = item.review_action or {}
    return {
        "collection_id": collection_id,
        "goal_id": item.scope_id if item.scope_type == "goal" else "",
        "scope_type": item.scope_type,
        "scope_id": item.scope_id,
        "sample_id": item.sample_id,
        "finding_id": item.finding_id,
        "claim_id": item.claim_id or "",
        "statement": _text(prediction.get("statement"))
        or _text(expert_target.get("statement")),
        "variables": _strings(prediction.get("variables")),
        "mediators": _strings(prediction.get("mediators")),
        "outcomes": _strings(prediction.get("outcomes")),
        "direction": _text(prediction.get("direction")),
        "scope_summary": _text(prediction.get("scope_summary")),
        "support_grade": _text(prediction.get("support_grade")),
        "review_status": _text(prediction.get("review_status")),
        "presentation_bucket": item.presentation_bucket,
        "trace_status": item.trace_status,
        "review_reasons": _strings(prediction.get("review_reasons")),
        "warnings": _strings(prediction.get("warnings")),
        "recommended_action": _text(review_action.get("label")),
        "recommended_action_code": _text(review_action.get("code")),
        "review_instructions": REVIEW_INSTRUCTIONS,
        "review_risk_flags": _review_risk_flags(
            _text(review_action.get("code")),
            _strings(prediction.get("review_reasons")),
            _strings(prediction.get("warnings")),
        ),
        "action": "skip",
        "allowed_actions": list(REVIEW_ACTION_OPTIONS),
        "issue_type": "",
        "reject_issue_options": list(REJECT_ISSUE_OPTIONS),
        "expert_note": "",
        "suggested_target": expert_target,
        "evidence": [_review_evidence_record(record) for record in evidence],
    }


def _review_risk_flags(
    recommended_action_code: str,
    review_reasons: list[str],
    warnings: list[str],
) -> list[str]:
    flags = []
    if recommended_action_code in REVIEW_RISK_FLAGS:
        flags.append(REVIEW_RISK_FLAGS[recommended_action_code])
    for value in [*review_reasons, *warnings]:
        if value in REVIEW_RISK_FLAGS and REVIEW_RISK_FLAGS[value] not in flags:
            flags.append(REVIEW_RISK_FLAGS[value])
    return flags


def _review_evidence_record(record: dict[str, Any]) -> dict[str, str]:
    return {
        "evidence_ref_id": _text(record.get("evidence_ref_id")),
        "label": _text(record.get("label"))
        or _text(record.get("source_label"))
        or _text(record.get("source_kind")),
        "source_ref": _text(record.get("source_ref")),
        "page": _text(record.get("page")),
        "href": _text(record.get("href")),
        "quote": _text(record.get("quote"))
        or _text(record.get("source_text"))
        or _text(record.get("training_source_text"))
        or _text(record.get("text")),
    }


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        text = _text(value)
        return [text] if text else []
    if isinstance(value, dict):
        return []
    try:
        return [text for item in value if (text := _text(item))]
    except TypeError:
        return []


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


@router.post(
    "/{collection_id}/research-understanding/feedback",
    response_model=ResearchUnderstandingFeedbackResponse,
    summary="记录 research understanding finding 专家反馈",
)
async def create_research_understanding_feedback(
    collection_id: str,
    payload: ResearchUnderstandingFeedbackCreateRequest,
    request: Request,
) -> ResearchUnderstandingFeedbackResponse:
    feedback = await run_in_threadpool(
        feedback_service.record_feedback,
        collection_id=collection_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        finding_id=payload.finding_id,
        claim_id=payload.claim_id,
        review_status=payload.review_status,
        issue_type=payload.issue_type,
        note=payload.note,
        reviewer=_reviewer_for_write(request, payload.reviewer),
    )
    return ResearchUnderstandingFeedbackResponse(**feedback.to_record())


@router.get(
    "/{collection_id}/research-understanding/feedback",
    response_model=ResearchUnderstandingFeedbackListResponse,
    summary="读取 research understanding finding 专家反馈",
)
async def list_research_understanding_feedback(
    collection_id: str,
    scope_type: str | None = Query(default=None, max_length=32),
    scope_id: str | None = Query(default=None, max_length=160),
    finding_id: str | None = Query(default=None, max_length=200),
    claim_id: str | None = Query(default=None, max_length=200),
) -> ResearchUnderstandingFeedbackListResponse:
    items = await run_in_threadpool(
        feedback_service.list_feedback,
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
        finding_id=finding_id,
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
    summary="记录 research understanding finding 专家校正",
)
async def create_research_understanding_curation(
    collection_id: str,
    payload: ResearchUnderstandingCurationCreateRequest,
    request: Request,
) -> ResearchUnderstandingCurationResponse:
    curation = await run_in_threadpool(
        feedback_service.record_curation,
        collection_id=collection_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        finding_id=payload.finding_id,
        claim_id=payload.claim_id,
        curated_claim_type=payload.curated_claim_type,
        curated_status=payload.curated_status,
        curated_statement=payload.curated_statement,
        curated_support_grade=payload.curated_support_grade,
        curated_review_status=payload.curated_review_status,
        curated_variables=payload.curated_variables,
        curated_mediators=payload.curated_mediators,
        curated_outcomes=payload.curated_outcomes,
        curated_direction=payload.curated_direction,
        curated_scope_summary=payload.curated_scope_summary,
        curated_evidence_ref_ids=payload.curated_evidence_ref_ids,
        curated_context_ids=payload.curated_context_ids,
        note=payload.note,
        reviewer=_reviewer_for_write(request, payload.reviewer),
    )
    return _curation_response(curation)


@router.get(
    "/{collection_id}/research-understanding/curations",
    response_model=ResearchUnderstandingCurationListResponse,
    summary="读取 research understanding finding 专家校正",
)
async def list_research_understanding_curations(
    collection_id: str,
    scope_type: str | None = Query(default=None, max_length=32),
    scope_id: str | None = Query(default=None, max_length=160),
    finding_id: str | None = Query(default=None, max_length=200),
    claim_id: str | None = Query(default=None, max_length=200),
) -> ResearchUnderstandingCurationListResponse:
    items = await run_in_threadpool(
        feedback_service.list_curations,
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
        finding_id=finding_id,
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


def _reviewer_for_write(request: Request, requested_reviewer: str | None) -> str:
    """Use session identity for human review, while preserving agent reviewers."""

    normalized_requested = (requested_reviewer or "").strip()
    if _is_agent_reviewer(normalized_requested):
        return normalized_requested
    user = require_current_user(request)
    return _current_user_reviewer(user)


def _is_agent_reviewer(reviewer: str) -> bool:
    normalized = reviewer.lower()
    return normalized.startswith("ai-reviewer") or normalized.startswith("agent-")


def _current_user_reviewer(user: dict[str, Any]) -> str:
    for key in ("email", "display_name", "user_id"):
        value = str(user.get(key) or "").strip()
        if value:
            return value
    raise ValueError("authenticated user has no reviewer identity")


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


@router.get(
    "/{collection_id}/research-understanding/dataset",
    response_model=ResearchUnderstandingDatasetResponse,
    summary="导出 research understanding finding 数据集样本",
)
async def export_research_understanding_dataset(
    collection_id: str,
    scope_type: str = Query(..., max_length=32),
    scope_id: str = Query(..., min_length=1, max_length=160),
    label_status: ResearchUnderstandingDatasetLabelStatus | None = Query(default=None),
    dataset_use_status: ResearchUnderstandingDatasetUseStatus | None = Query(default=None),
    format: ResearchUnderstandingDatasetExportFormat = Query(default="json"),
) -> ResearchUnderstandingDatasetResponse | Response:
    dataset = await run_in_threadpool(
        feedback_service.export_dataset,
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
        label_status=label_status,
        dataset_use_status=dataset_use_status,
    )
    response = ResearchUnderstandingDatasetResponse(**dataset)
    if format == "jsonl":
        return _dataset_jsonl_response(response)
    if format == "messages_jsonl":
        return _dataset_jsonl_response(response, messages_only=True)
    if format == "review_jsonl":
        return _dataset_review_jsonl_response(response)
    return response


@router.get(
    "/{collection_id}/research-understanding/dataset/collection",
    response_model=ResearchUnderstandingDatasetResponse,
    summary="导出 collection 级 research understanding finding 数据集样本",
)
async def export_collection_research_understanding_dataset(
    collection_id: str,
    scope_type: str = Query(default="goal", max_length=32),
    label_status: ResearchUnderstandingDatasetLabelStatus | None = Query(default=None),
    dataset_use_status: ResearchUnderstandingDatasetUseStatus | None = Query(default=None),
    format: ResearchUnderstandingDatasetExportFormat = Query(default="json"),
) -> ResearchUnderstandingDatasetResponse | Response:
    dataset = await run_in_threadpool(
        feedback_service.export_collection_dataset,
        collection_id=collection_id,
        scope_type=scope_type,
        label_status=label_status,
        dataset_use_status=dataset_use_status,
    )
    response = ResearchUnderstandingDatasetResponse(**dataset)
    if format == "jsonl":
        return _dataset_jsonl_response(response)
    if format == "messages_jsonl":
        return _dataset_jsonl_response(response, messages_only=True)
    if format == "review_jsonl":
        return _dataset_review_jsonl_response(response)
    return response
