"""Authenticated HTTP boundary for Research Agent Chat sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from application.chat.session_service import (
    ChatApprovalPendingError,
    ChatSessionNotFoundError,
    ChatSourceContextError,
)
from controllers.dependencies.auth import current_user_id
from controllers.schemas.chat.session import (
    ChatMessageListResponse,
    ChatMessageResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
    ChatToolCallResponse,
    ChatToolDecisionRequest,
    ChatTurnRequest,
    ChatTurnResponse,
)
from domain.chat import ChatSourceContext


router = APIRouter(prefix="/chat-sessions", tags=["chat-sessions"])


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
        messages = await request.app.state.chat_session_service.list_messages_for_user(
            session_id,
            await current_user_id(request),
        )
        pending = await request.app.state.chat_session_service.get_pending_approval_for_user(
            session_id,
            await current_user_id(request),
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_session_not_found(exc)) from exc
    return ChatMessageListResponse(
        items=[_message_response(item) for item in messages],
        pending_approval=(
            ChatToolCallResponse.model_validate(pending.to_record())
            if pending is not None
            else None
        ),
    )


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
            events = await request.app.state.chat_session_service.stream_message_for_user(
                session_id,
                user_id,
                message=payload.message,
                source_contexts=_source_contexts(payload),
            )
            return StreamingResponse(
                _chat_event_stream(events),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        turn = await request.app.state.chat_session_service.post_message_for_user(
            session_id,
            user_id,
            message=payload.message,
            source_contexts=_source_contexts(payload),
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
