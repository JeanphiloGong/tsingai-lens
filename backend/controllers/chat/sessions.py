"""Authenticated HTTP boundary for Research Agent Chat sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from application.chat.session_service import (
    ChatApprovalPendingError,
    ChatBranchAlreadyStartedError,
    ChatMessageNotFoundError,
    ChatSessionNotFoundError,
    ChatSourceContextError,
)
from application.evaluation.chat_correction_review_service import (
    ChatCorrectionReviewStaleError,
    ChatCorrectionSampleNotFoundError,
)
from application.evaluation.chat_correction_candidate_service import (
    ChatCorrectionCandidateNotFoundError,
    ChatCorrectionCandidateService,
    ChatCorrectionCandidateUnavailableError,
)
from application.repositories.chat_repository import ChatSessionBusyError
from controllers.dependencies.auth import current_user_id
from controllers.schemas.chat.session import (
    ChatPermissionRequest,
    ChatPermissionResponse,
    ChatMessageFeedbackRequest,
    ChatBranchRequest,
    ChatMessageFeedbackResponse,
    ChatMessageListResponse,
    ChatMessageResponse,
    ChatModelCallListResponse,
    ChatModelCallResponse,
    ChatModelCallSummaryResponse,
    ChatCorrectionCaseCreateRequest,
    ChatCorrectionCaseListResponse,
    ChatCorrectionCaseResponse,
    ChatCorrectionCandidateCreateRequest,
    ChatCorrectionCandidateListResponse,
    ChatCorrectionCandidateResponse,
    ChatCorrectionReviewCreateRequest,
    ChatCorrectionReviewListResponse,
    ChatCorrectionReviewResponse,
    ChatCorrectionReviewStatusResponse,
    ChatCorrectionSampleListResponse,
    ChatCorrectionSampleResponse,
    ChatResponseSnapshotResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
    ChatToolCallResponse,
    ChatToolDecisionRequest,
    ChatTurnRequest,
    ChatTurnResponse,
    ChatTreeResponse,
    ChatTreeNodeResponse,
)
from domain.chat import ChatSourceContext, ToolPermissionMode


router = APIRouter(prefix="/chat-sessions", tags=["chat-sessions"])


@router.get("/{session_id}/permissions", response_model=ChatPermissionResponse)
async def get_chat_permission(session_id: str, request: Request):
    service = request.app.state.chat_session_service
    user_id = await current_user_id(request)
    try:
        await service.get_session_for_user(session_id, user_id)
        return await service.repository.read_permission(session_id, user_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{session_id}/permissions", response_model=ChatPermissionResponse)
async def set_chat_permission(session_id: str, payload: ChatPermissionRequest, request: Request):
    service = request.app.state.chat_session_service
    user_id = await current_user_id(request)
    try:
        await service.get_session_for_user(session_id, user_id)
        return await service.repository.set_permission(session_id, user_id, **payload.model_dump())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


def _session_not_found(exc: ChatSessionNotFoundError) -> dict[str, str]:
    return {
        "code": "chat_session_not_found",
        "message": str(exc),
        "session_id": exc.session_id,
    }


@router.post(
    "",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a collection-bound Research Agent Chat session",
)
async def create_chat_session(
    payload: ChatSessionCreateRequest,
    request: Request,
) -> ChatSessionResponse:
    try:
        session = await request.app.state.chat_session_service.create_session(
            collection_id=payload.collection_id,
            user_id=await current_user_id(request),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ChatSessionResponse.model_validate(session.to_record())


@router.get(
    "/{session_id}/model-calls",
    response_model=ChatModelCallListResponse,
    summary="List exact provider calls for one owned Chat session",
)
async def list_chat_model_calls(
    session_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ChatModelCallListResponse:
    try:
        calls = await request.app.state.chat_session_service.list_model_calls_for_user(
            session_id, await current_user_id(request), limit=limit, offset=offset,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    return ChatModelCallListResponse(
        items=[ChatModelCallSummaryResponse.model_validate(vars(call)) for call in calls],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{session_id}/model-calls/{call_id}",
    response_model=ChatModelCallResponse,
    summary="Read one exact provider request for an owned Chat session",
)
async def get_chat_model_call(
    session_id: str, call_id: str, request: Request
) -> ChatModelCallResponse:
    try:
        call = await request.app.state.chat_session_service.get_model_call_for_user(
            session_id, call_id, await current_user_id(request),
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    if call is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "chat_model_call_not_found", "call_id": call_id},
        )
    return ChatModelCallResponse.model_validate(vars(call))


@router.post(
    "/{session_id}/correction-cases",
    response_model=ChatCorrectionCaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link an explicit Chat correction sequence",
)
async def create_chat_correction_case(
    session_id: str,
    payload: ChatCorrectionCaseCreateRequest,
    request: Request,
) -> ChatCorrectionCaseResponse:
    try:
        case = await request.app.state.chat_session_service.link_correction_case_for_user(
            session_id,
            await current_user_id(request),
            original_message_id=payload.original_message_id,
            feedback_message_id=payload.feedback_message_id,
            corrected_message_id=payload.corrected_message_id,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "chat_correction_case_invalid", "message": str(exc)},
        ) from exc
    return ChatCorrectionCaseResponse.model_validate(case.to_record())


@router.get(
    "/{session_id}/correction-cases",
    response_model=ChatCorrectionCaseListResponse,
    summary="List explicit correction links for an owned Chat session",
)
async def list_chat_correction_cases(
    session_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ChatCorrectionCaseListResponse:
    try:
        cases = await request.app.state.chat_session_service.list_correction_cases_for_user(
            session_id, await current_user_id(request), limit=limit, offset=offset,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    return ChatCorrectionCaseListResponse(
        items=[ChatCorrectionCaseResponse.model_validate(case.to_record()) for case in cases],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{session_id}/correction-cases/{case_id}",
    response_model=ChatCorrectionCaseResponse,
    summary="Read one explicit correction link",
)
async def get_chat_correction_case(
    session_id: str, case_id: str, request: Request
) -> ChatCorrectionCaseResponse:
    try:
        case = await request.app.state.chat_session_service.get_correction_case_for_user(
            session_id, case_id, await current_user_id(request),
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    if case is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "chat_correction_case_not_found", "case_id": case_id},
        )
    return ChatCorrectionCaseResponse.model_validate(case.to_record())


def _chat_correction_candidate_service(request: Request) -> ChatCorrectionCandidateService:
    service = getattr(request.app.state, "chat_correction_candidate_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "chat_correction_candidate_unavailable",
                "message": "Chat correction candidate generation is unavailable.",
            },
        )
    return service


@router.post(
    "/{session_id}/correction-candidates",
    response_model=ChatCorrectionCandidateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Propose a correction candidate from one owned saved Chat turn",
)
async def create_chat_correction_candidate(
    session_id: str,
    payload: ChatCorrectionCandidateCreateRequest,
    request: Request,
) -> ChatCorrectionCandidateResponse:
    service = _chat_correction_candidate_service(request)
    try:
        candidate = await service.propose_for_user(
            session_id,
            await current_user_id(request),
            challenge_message_id=payload.challenge_message_id,
            answer_message_id=payload.answer_message_id,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "chat_correction_candidate_invalid", "message": str(exc)},
        ) from exc
    return ChatCorrectionCandidateResponse.model_validate(candidate.to_record())


@router.get(
    "/{session_id}/correction-candidates",
    response_model=ChatCorrectionCandidateListResponse,
    summary="List correction candidate proposals for an owned Chat session",
)
async def list_chat_correction_candidates(
    session_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ChatCorrectionCandidateListResponse:
    service = _chat_correction_candidate_service(request)
    try:
        candidates = await service.list_for_user(
            session_id, await current_user_id(request), limit=limit, offset=offset
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    return ChatCorrectionCandidateListResponse(
        items=[ChatCorrectionCandidateResponse.model_validate(item.to_record()) for item in candidates],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{session_id}/correction-candidates/{candidate_id}",
    response_model=ChatCorrectionCandidateResponse,
    summary="Read one correction candidate proposal",
)
async def get_chat_correction_candidate(
    session_id: str, candidate_id: str, request: Request
) -> ChatCorrectionCandidateResponse:
    service = _chat_correction_candidate_service(request)
    try:
        candidate = await service.get_for_user(
            session_id, candidate_id, await current_user_id(request)
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    if candidate is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "chat_correction_candidate_not_found", "candidate_id": candidate_id},
        )
    return ChatCorrectionCandidateResponse.model_validate(candidate.to_record())


@router.post(
    "/{session_id}/correction-candidates/{candidate_id}/select",
    response_model=ChatCorrectionCandidateResponse,
    summary="Select a candidate and import it into the P2/P3 review path",
)
async def select_chat_correction_candidate(
    session_id: str, candidate_id: str, request: Request
) -> ChatCorrectionCandidateResponse:
    service = _chat_correction_candidate_service(request)
    try:
        candidate = await service.select_for_user(
            session_id, candidate_id, await current_user_id(request)
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except ChatCorrectionCandidateNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "chat_correction_candidate_not_found", "candidate_id": str(exc)},
        ) from exc
    except ChatCorrectionCandidateUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "chat_correction_candidate_unavailable", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "chat_correction_candidate_not_selectable", "message": str(exc)},
        ) from exc
    return ChatCorrectionCandidateResponse.model_validate(candidate.to_record())


def _chat_correction_review_service(request: Request):
    service = getattr(request.app.state, "chat_correction_review_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "chat_correction_review_unavailable",
                "message": "Chat correction review storage is unavailable.",
            },
        )
    return service


@router.get(
    "/{session_id}/correction-samples",
    response_model=ChatCorrectionSampleListResponse,
    summary="List reviewed Chat correction samples for an owned session",
)
async def list_chat_correction_samples(
    session_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ChatCorrectionSampleListResponse:
    service = _chat_correction_review_service(request)
    try:
        samples = await service.list_samples_for_user(
            session_id, await current_user_id(request), limit=limit, offset=offset
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    return ChatCorrectionSampleListResponse(
        items=[ChatCorrectionSampleResponse.model_validate(item.to_record()) for item in samples],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{session_id}/correction-cases/{case_id}/sample",
    response_model=ChatCorrectionSampleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Freeze one linked Chat correction case for review",
)
async def create_chat_correction_sample(
    session_id: str, case_id: str, request: Request
) -> ChatCorrectionSampleResponse:
    service = _chat_correction_review_service(request)
    try:
        sample = await service.create_sample_for_user(
            session_id, case_id, await current_user_id(request)
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except ChatCorrectionSampleNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "chat_correction_sample_not_found", "message": str(exc)}) from exc
    except ChatCorrectionReviewStaleError as exc:
        raise HTTPException(status_code=409, detail={"code": "chat_correction_sample_stale", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "chat_correction_sample_invalid", "message": str(exc)}) from exc
    return ChatCorrectionSampleResponse.model_validate(sample.to_record())


@router.get(
    "/{session_id}/correction-samples/{sample_id}",
    response_model=ChatCorrectionSampleResponse,
    summary="Read one owned Chat correction sample",
)
async def get_chat_correction_sample(
    session_id: str, sample_id: str, request: Request
) -> ChatCorrectionSampleResponse:
    service = _chat_correction_review_service(request)
    try:
        sample = await service.get_sample_for_user(
            session_id, sample_id, await current_user_id(request)
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    if sample is None:
        raise HTTPException(status_code=404, detail={"code": "chat_correction_sample_not_found", "sample_id": sample_id})
    return ChatCorrectionSampleResponse.model_validate(sample.to_record())


@router.get(
    "/{session_id}/correction-samples/{sample_id}/reviews",
    response_model=ChatCorrectionReviewListResponse,
    summary="List append-only Chat correction reviews",
)
async def list_chat_correction_reviews(
    session_id: str, sample_id: str, request: Request
) -> ChatCorrectionReviewListResponse:
    service = _chat_correction_review_service(request)
    try:
        reviews = await service.list_reviews_for_user(
            session_id, sample_id, await current_user_id(request)
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except ChatCorrectionSampleNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "chat_correction_sample_not_found", "message": str(exc)}) from exc
    return ChatCorrectionReviewListResponse(
        items=[ChatCorrectionReviewResponse.model_validate(item.to_record()) for item in reviews]
    )


@router.post(
    "/{session_id}/correction-samples/{sample_id}/reviews",
    response_model=ChatCorrectionReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record an owner Chat correction review decision",
)
async def review_chat_correction_sample(
    session_id: str,
    sample_id: str,
    payload: ChatCorrectionReviewCreateRequest,
    request: Request,
) -> ChatCorrectionReviewResponse:
    service = _chat_correction_review_service(request)
    try:
        review = await service.review_sample_for_user(
            session_id,
            sample_id,
            await current_user_id(request),
            decision=payload.decision,
            reason=payload.reason,
            support_message_ids=payload.support_message_ids,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except ChatCorrectionSampleNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "chat_correction_sample_not_found", "message": str(exc)}) from exc
    except ChatCorrectionReviewStaleError as exc:
        raise HTTPException(status_code=409, detail={"code": "chat_correction_sample_stale", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "chat_correction_review_invalid", "message": str(exc)}) from exc
    return ChatCorrectionReviewResponse.model_validate(review.to_record())


@router.get(
    "/{session_id}/correction-samples/{sample_id}/review-status",
    response_model=ChatCorrectionReviewStatusResponse,
    summary="Read the current Chat correction review status",
)
async def get_chat_correction_review_status(
    session_id: str, sample_id: str, request: Request
) -> ChatCorrectionReviewStatusResponse:
    service = _chat_correction_review_service(request)
    try:
        value = await service.status_for_user(
            session_id, sample_id, await current_user_id(request)
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except ChatCorrectionSampleNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "chat_correction_sample_not_found", "message": str(exc)}) from exc
    return ChatCorrectionReviewStatusResponse.model_validate(value)


@router.get(
    "/{session_id}",
    response_model=ChatSessionResponse,
    summary="Read one owned Research Agent Chat session",
)
async def get_chat_session(
    session_id: str,
    request: Request,
) -> ChatSessionResponse:
    try:
        session = await request.app.state.chat_session_service.get_session_for_user(
            session_id,
            await current_user_id(request),
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    return ChatSessionResponse.model_validate(session.to_record())


@router.post("/{session_id}/branches", response_model=ChatSessionResponse, status_code=201)
async def branch_chat_message(
    session_id: str, payload: ChatBranchRequest, request: Request,
) -> ChatSessionResponse:
    try:
        session = await request.app.state.chat_session_service.branch_message_for_user(
            session_id, payload.message_id, await current_user_id(request),
            request_id=str(payload.request_id), message=payload.message,
            mode=payload.mode,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ChatSessionBusyError, ChatApprovalPendingError) as exc:
        raise HTTPException(status_code=409, detail={"code": "chat_session_busy", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "chat_branch_invalid", "message": str(exc)}) from exc
    return ChatSessionResponse.model_validate(session.to_record())


@router.get("/{session_id}/tree", response_model=ChatTreeResponse)
async def get_chat_tree(session_id: str, request: Request) -> ChatTreeResponse:
    try:
        tree = await request.app.state.chat_session_service.get_tree_for_user(
            session_id, await current_user_id(request),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ChatTreeResponse(
        root_session_id=tree["root_session_id"], active_path=tree["active_path"],
        nodes=[ChatTreeNodeResponse(**{**node, "message": _message_response(node["message"])})
               for node in tree["nodes"]],
    )


@router.get(
    "/{session_id}/messages",
    response_model=ChatMessageListResponse,
    summary="List one owned Chat trajectory",
)
async def list_chat_messages(
    session_id: str,
    request: Request,
) -> ChatMessageListResponse:
    try:
        user_id = await current_user_id(request)
        trajectory = await request.app.state.chat_session_service.get_trajectory_for_user(session_id, user_id)
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _trajectory_response(trajectory)


@router.get("/{session_id}/events", summary="Resume updates for one owned Research Agent response")
async def stream_chat_updates(
    session_id: str, request: Request, response_id: str = Query(min_length=1, max_length=128),
) -> StreamingResponse:
    try:
        events = await request.app.state.chat_session_service.stream_updates_for_user(
            session_id, await current_user_id(request), response_id=response_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(
        _chat_event_stream(events), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _snapshot_response(snapshot: Any) -> ChatResponseSnapshotResponse:
    return ChatResponseSnapshotResponse.model_validate(vars(snapshot))


def _trajectory_response(trajectory: Mapping[str, Any]) -> ChatMessageListResponse:
    pending = trajectory["pending_approval"]
    response = trajectory.get("response")
    return ChatMessageListResponse(
        items=[_message_response(item) for item in trajectory["messages"]],
        feedback=[ChatMessageFeedbackResponse.model_validate(item) for item in trajectory["feedback"]],
        branches=trajectory["branches"],
        branch_draft=_message_response(trajectory["branch_draft"]) if trajectory["branch_draft"] else None,
        running=trajectory["running"],
        response=_snapshot_response(response) if response is not None else None,
        pending_approval=(
            ChatToolCallResponse.model_validate(pending.to_record())
            if pending is not None
            else None
        ),
    )


@router.put(
    "/{session_id}/messages/{message_id}/feedback",
    response_model=ChatMessageFeedbackResponse | None,
    summary="Set or withdraw usefulness feedback on an owned assistant answer",
)
async def set_chat_message_feedback(
    session_id: str,
    message_id: str,
    payload: ChatMessageFeedbackRequest,
    request: Request,
) -> ChatMessageFeedbackResponse | None:
    try:
        feedback = await request.app.state.chat_session_service.set_message_feedback_for_user(
            session_id, message_id, await current_user_id(request),
            rating=payload.rating, reason=payload.reason, comment=payload.comment,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except ChatMessageNotFoundError as exc:
        raise HTTPException(status_code=404, detail={
            "code": "chat_message_not_found", "message": str(exc),
        }) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={
            "code": "chat_feedback_invalid", "message": str(exc),
        }) from exc
    return ChatMessageFeedbackResponse.model_validate(feedback) if feedback else None


@router.post(
    "/{session_id}/messages",
    response_model=ChatTurnResponse,
    summary="Run one Research Agent turn",
)
async def post_chat_message(
    session_id: str,
    payload: ChatTurnRequest,
    request: Request,
) -> ChatTurnResponse | StreamingResponse:
    try:
        user_id = await current_user_id(request)
        if "text/event-stream" in request.headers.get("accept", ""):
            permission_kwargs = (
                {"permission_mode": payload.permission_mode}
                if payload.permission_mode is not ToolPermissionMode.CONFIRM
                else {}
            )
            events = await request.app.state.chat_session_service.stream_message_for_user(
                session_id,
                user_id,
                message=payload.message,
                source_contexts=_source_contexts(payload),
                **permission_kwargs,
                **({"branch_revision": True} if payload.branch_revision else {}),
            )
            return StreamingResponse(
                _chat_event_stream(events),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        permission_kwargs = (
            {"permission_mode": payload.permission_mode}
            if payload.permission_mode is not ToolPermissionMode.CONFIRM
            else {}
        )
        turn = await request.app.state.chat_session_service.post_message_for_user(
            session_id,
            user_id,
            message=payload.message,
            source_contexts=_source_contexts(payload),
            **permission_kwargs,
            **({"branch_revision": True} if payload.branch_revision else {}),
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except ChatApprovalPendingError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "chat_tool_approval_pending",
                "message": str(exc),
                "tool_call_id": exc.tool_call_id,
            },
        ) from exc
    except ChatSessionBusyError as exc:
        raise HTTPException(status_code=409, detail={"code": "chat_session_busy", "message": str(exc)}) from exc
    except ChatBranchAlreadyStartedError as exc:
        raise HTTPException(status_code=409, detail={"code": "chat_branch_already_started", "message": str(exc)}) from exc
    except ChatSourceContextError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "chat_source_context_invalid",
                "message": str(exc),
            },
        ) from exc
    return _turn_response(turn)


def _source_contexts(payload: ChatTurnRequest) -> tuple[ChatSourceContext, ...]:
    try:
        return tuple(
            ChatSourceContext.from_mapping(item.model_dump())
            for item in payload.source_contexts
        )
    except ValueError as exc:
        raise ChatSourceContextError("selected Source context is invalid") from exc


async def _chat_event_stream(
    events: AsyncIterator[Mapping[str, Any]],
) -> AsyncIterator[str]:
    async for item in events:
        event_type = str(item.get("type") or "error")
        if event_type == "turn":
            data: Any = _turn_response(item.get("turn") or {}).model_dump(mode="json")
        elif event_type == "text_delta":
            data = {"content": str(item.get("content") or "")}
        elif event_type == "progress":
            data = dict(item.get("progress") or {})
        elif event_type == "snapshot":
            data = _snapshot_response(item["snapshot"]).model_dump(mode="json")
        elif event_type == "trajectory":
            data = _trajectory_response(item["trajectory"]).model_dump(mode="json")
        else:
            event_type = "error"
            data = item.get("error") or {
                "code": "chat_stream_failed",
                "message": "The research response could not be completed.",
            }
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        yield f"event: {event_type}\ndata: {payload}\n\n"


@router.post(
    "/{session_id}/tool-calls/{tool_call_id}/decision",
    response_model=ChatTurnResponse,
    summary="Approve or reject one exact Research Agent write call",
)
async def decide_chat_tool_call(
    session_id: str,
    tool_call_id: str,
    payload: ChatToolDecisionRequest,
    request: Request,
) -> ChatTurnResponse:
    try:
        turn = await request.app.state.chat_session_service.decide_tool_call_for_user(
            session_id,
            tool_call_id,
            await current_user_id(request),
            arguments_digest=payload.arguments_digest,
            decision=payload.decision,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    except ChatSessionBusyError as exc:
        raise HTTPException(status_code=409, detail={"code": "chat_session_busy", "message": str(exc)}) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "chat_tool_call_not_found",
                "message": str(exc),
                "tool_call_id": tool_call_id,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "chat_tool_decision_conflict",
                "message": str(exc),
                "tool_call_id": tool_call_id,
            },
        ) from exc
    return _turn_response(turn)


def _turn_response(turn: Mapping[str, Any]) -> ChatTurnResponse:
    pending = turn.get("pending_approval")
    return ChatTurnResponse(
        status=str(turn["status"]),
        completion_reason=turn.get("completion_reason"),
        warnings=list(turn.get("warnings") or ()),
        messages=[_message_response(item) for item in turn.get("messages") or ()],
        pending_approval=(
            ChatToolCallResponse.model_validate(pending.to_record())
            if pending is not None
            else None
        ),
        error_code=(
            str(turn["error_code"]) if turn.get("error_code") is not None else None
        ),
    )


def _message_response(message: Any) -> ChatMessageResponse:
    return ChatMessageResponse.model_validate(message.to_record())


__all__ = ["router"]
