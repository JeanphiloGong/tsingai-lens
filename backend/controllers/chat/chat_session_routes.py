"""Authenticated HTTP boundary for Research Agent Chat sessions."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Annotated, Any, Mapping

from application.chat.inline_citations import format_message_citations
from application.chat.session_service import ChatSourceContextError
from controllers.chat.schemas import (
    ChatBranchRequest,
    ChatMessageFeedbackRequest,
    ChatMessageFeedbackResponse,
    ChatMessageListResponse,
    ChatMessageResponse,
    ChatModelCallResponse,
    ChatModelCallSummaryResponse,
    ChatPermissionRequest,
    ChatPermissionResponse,
    ChatResponseSnapshotResponse,
    ChatSessionCreateRequest,
    ChatSessionListResponse,
    ChatSessionPinRequest,
    ChatSessionResponse,
    ChatSessionTitleRequest,
    ChatToolCallResponse,
    ChatToolDecisionRequest,
    ChatTreeNodeResponse,
    ChatTreeResponse,
    ChatTurnResponse,
    SendChatMessageRequest,
)
from controllers.dependencies.auth import get_current_user_id
from domain.chat import ChatResourceRef, ChatSourceContext
from exceptions import ProjectException
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse
from utils.response import ApiResponse, make_api_response

logger = logging.getLogger(__name__)

chat_session_router = APIRouter(prefix="/chat-sessions", tags=["chat-sessions"])


@chat_session_router.get(
    "/{session_id}/permissions", response_model=ApiResponse[ChatPermissionResponse]
)
async def get_chat_permission(
    request: Request,
    session_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
):
    return make_api_response(
        data=await request.app.state.runtime.chat_session_service.get_permission_for_user(session_id, user_id)
    )



@chat_session_router.put(
    "/{session_id}/permissions", response_model=ApiResponse[ChatPermissionResponse]
)
async def set_chat_permission(
    request: Request,
    session_id: str,
    payload: ChatPermissionRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
):
    return make_api_response(
        data=await request.app.state.runtime.chat_session_service.set_permission_for_user(
            session_id, user_id, **payload.model_dump()
        )
    )



@chat_session_router.get(
    "",
    response_model=ApiResponse[ChatSessionListResponse],
    summary="List owned Chat sessions",
)
async def list_chat_sessions(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    collection_id: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Response:
    sessions = await request.app.state.runtime.chat_session_service.list_sessions_for_user(
        collection_id=collection_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return make_api_response(
        data=ChatSessionListResponse(
            items=[
                ChatSessionResponse(**{**asdict(item.session), "title": item.title})
                for item in sessions
            ],
            limit=limit,
            offset=offset,
        )
    )



@chat_session_router.post(
    "",
    response_model=ApiResponse[ChatSessionResponse],
    status_code=200,
    summary="Create a collection-bound Research Agent Chat session",
)
async def create_chat_session(
    request: Request,
    payload: ChatSessionCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    session = await request.app.state.runtime.chat_session_service.create_session(
        collection_id=payload.collection_id,
        user_id=user_id,
    )
    return make_api_response(
        data=ChatSessionResponse.model_validate(session, from_attributes=True)
    )



@chat_session_router.get(
    "/{session_id}",
    response_model=ApiResponse[ChatSessionResponse],
    summary="Read one owned Research Agent Chat session",
)
async def get_chat_session(
    request: Request,
    session_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    session = await request.app.state.runtime.chat_session_service.get_session_for_user(
        session_id,
        user_id,
    )
    return make_api_response(
        data=ChatSessionResponse.model_validate(session, from_attributes=True)
    )



@chat_session_router.put(
    "/{session_id}/pin",
    response_model=ApiResponse[ChatSessionResponse],
    summary="Pin or unpin one owned Chat session",
)
async def set_chat_session_pin(
    request: Request,
    session_id: str,
    payload: ChatSessionPinRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    session = await request.app.state.runtime.chat_session_service.set_session_pin_for_user(
        session_id,
        user_id,
        is_pinned=payload.is_pinned,
    )
    return make_api_response(
        data=ChatSessionResponse.model_validate(session, from_attributes=True)
    )



@chat_session_router.put(
    "/{session_id}/title",
    response_model=ApiResponse[ChatSessionResponse],
    summary="Rename one owned Chat session",
)
async def set_chat_session_title(
    request: Request,
    session_id: str,
    payload: ChatSessionTitleRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    session = await request.app.state.runtime.chat_session_service.set_session_title_for_user(
        session_id,
        user_id,
        title=payload.title,
    )
    return make_api_response(
        data=ChatSessionResponse.model_validate(session, from_attributes=True)
    )



@chat_session_router.delete(
    "/{session_id}",
    status_code=200,
    summary="Delete one owned Research Agent Chat session",
    response_model=ApiResponse[dict],
)
async def delete_chat_session(
    request: Request,
    session_id: str, user_id: Annotated[str, Depends(get_current_user_id)]
) -> Response:
    await request.app.state.runtime.chat_session_service.delete_session_for_user(session_id, user_id)
    return make_api_response()



@chat_session_router.post(
    "/{session_id}/branches",
    response_model=ApiResponse[ChatSessionResponse],
    status_code=200,
)
async def branch_chat_message(
    request: Request,
    session_id: str,
    payload: ChatBranchRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    session = await request.app.state.runtime.chat_session_service.branch_message_for_user(
        session_id,
        payload.message_id,
        user_id,
        request_id=str(payload.request_id),
        message=payload.message,
        mode=payload.mode,
    )
    return make_api_response(
        data=ChatSessionResponse.model_validate(session, from_attributes=True)
    )



@chat_session_router.get(
    "/{session_id}/tree", response_model=ApiResponse[ChatTreeResponse]
)
async def get_chat_tree(
    request: Request,
    session_id: str, user_id: Annotated[str, Depends(get_current_user_id)]
) -> Response:
    tree = await request.app.state.runtime.chat_session_service.get_tree_for_user(
        session_id,
        user_id,
    )
    return make_api_response(
        data=ChatTreeResponse(
            root_session_id=tree["root_session_id"],
            active_path=tree["active_path"],
            nodes=[
                ChatTreeNodeResponse(
                    **{
                        **node,
                        "message": ChatMessageResponse.model_validate(
                            node["message"], from_attributes=True
                        ),
                    }
                )
                for node in tree["nodes"]
            ],
        )
    )



@chat_session_router.get(
    "/{session_id}/messages",
    response_model=ApiResponse[ChatMessageListResponse],
    summary="List one owned Chat trajectory",
)
async def list_chat_messages(
    request: Request,
    session_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    trajectory = await request.app.state.runtime.chat_session_service.get_trajectory_for_user(session_id, user_id)
    return make_api_response(data=_trajectory_response(trajectory))



@chat_session_router.get(
    "/{session_id}/model-calls",
    response_model=ApiResponse[dict],
    summary="List exact provider calls for an owned Chat session",
)
async def list_chat_model_calls(
    request: Request,
    session_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Response:
    calls = await request.app.state.runtime.chat_session_service.list_model_calls_for_user(
        session_id,
        user_id,
        limit=limit,
        offset=offset,
    )
    return make_api_response(
        data={
            "items": [
                ChatModelCallSummaryResponse.model_validate(
                    call, from_attributes=True
                ).model_dump()
                for call in calls
            ],
            "limit": limit,
            "offset": offset,
        }
    )



@chat_session_router.get(
    "/{session_id}/model-calls/{call_id}",
    response_model=ApiResponse[ChatModelCallResponse],
    summary="Read one exact provider call for an owned Chat session",
)
async def get_chat_model_call(
    request: Request,
    session_id: str,
    call_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    call = await request.app.state.runtime.chat_session_service.get_model_call_for_user(
        session_id,
        call_id,
        user_id,
    )
    return make_api_response(
        data=ChatModelCallResponse.model_validate(call, from_attributes=True)
    )



@chat_session_router.get(
    "/{session_id}/events",
    summary="Resume updates for one owned Research Agent response",
)
async def stream_chat_updates(
    request: Request,
    session_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    response_id: str = Query(min_length=1, max_length=128),
) -> Response:
    events = await request.app.state.runtime.chat_session_service.stream_updates_for_user(
        session_id,
        user_id,
        response_id=response_id,
    )
    return StreamingResponse(
        _chat_event_stream(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )



def _trajectory_response(trajectory: Mapping[str, Any]) -> ChatMessageListResponse:
    pending = trajectory["pending_approval"]
    response = trajectory.get("response")
    visible_messages = format_message_citations(trajectory["messages"])
    return ChatMessageListResponse(
        items=[
            ChatMessageResponse.model_validate(item, from_attributes=True)
            for item in visible_messages
        ],
        feedback=[
            ChatMessageFeedbackResponse.model_validate(item)
            for item in trajectory["feedback"]
        ],
        branches=trajectory["branches"],
        branch_draft=(
            ChatMessageResponse.model_validate(
                trajectory["branch_draft"], from_attributes=True
            )
            if trajectory["branch_draft"]
            else None
        ),
        running=trajectory["running"],
        response=(
            ChatResponseSnapshotResponse.model_validate(response, from_attributes=True)
            if response is not None
            else None
        ),
        pending_approval=(
            ChatToolCallResponse.model_validate(pending, from_attributes=True)
            if pending is not None
            else None
        ),
    )


@chat_session_router.put(
    "/{session_id}/messages/{message_id}/feedback",
    response_model=ApiResponse[ChatMessageFeedbackResponse | None],
    summary="Set or withdraw usefulness feedback on an owned assistant answer",
)
async def set_chat_message_feedback(
    request: Request,
    session_id: str,
    message_id: str,
    payload: ChatMessageFeedbackRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    feedback = await request.app.state.runtime.chat_session_service.set_message_feedback_for_user(
        session_id,
        message_id,
        user_id,
        rating=payload.rating,
        reason=payload.reason,
        comment=payload.comment,
    )
    return make_api_response(
        data=ChatMessageFeedbackResponse.model_validate(feedback) if feedback else None
    )



@chat_session_router.post(
    "/{session_id}/messages",
    response_model=ApiResponse[ChatTurnResponse],
    summary="Run one Research Agent turn",
)
async def send_chat_message(
    session_id: str,
    payload: SendChatMessageRequest,
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    source_contexts = _map_source_contexts(payload)
    if "text/event-stream" in request.headers.get("accept", ""):
        events = await request.app.state.runtime.chat_session_service.send_message_stream(
            session_id,
            user_id,
            message=payload.message,
            source_contexts=source_contexts,
            permission_mode=payload.permission_mode,
            branch_revision=payload.branch_revision,
        )
        return StreamingResponse(
            _chat_event_stream(events),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    turn = await request.app.state.runtime.chat_session_service.send_message(
        session_id,
        user_id,
        message=payload.message,
        source_contexts=source_contexts,
        permission_mode=payload.permission_mode,
        branch_revision=payload.branch_revision,
    )
    return make_api_response(data=_turn_response(turn))



def _map_source_contexts(
    payload: SendChatMessageRequest,
) -> tuple[ChatSourceContext, ...]:
    try:
        return tuple(
            ChatSourceContext(
                resource_ref=ChatResourceRef(
                    resource_type=item.resource_ref.resource_type,
                    resource_id=item.resource_ref.resource_id,
                    href=item.resource_ref.href,
                ),
                collection_id=item.collection_id,
                document_id=item.document_id,
                document_title=item.document_title,
                source_kind=item.source_kind,
                source_ref=item.source_ref,
                page=item.page,
                quote=item.quote,
                heading_path=item.heading_path,
                quote_truncated=item.quote_truncated,
                source_digest=item.source_digest,
            )
            for item in payload.source_contexts
        )
    except ValueError as exc:
        raise ChatSourceContextError("selected Source context is invalid") from exc


async def _chat_event_stream(
    events: AsyncIterator[Mapping[str, Any]],
) -> AsyncIterator[str]:
    try:
        async for item in events:
            event_type = str(item.get("type") or "error")
            if event_type == "turn":
                data: Any = _turn_response(item.get("turn") or {}).model_dump(
                    mode="json"
                )
            elif event_type == "text_delta":
                data = {"content": str(item.get("content") or "")}
            elif event_type == "progress":
                data = dict(item.get("progress") or {})
            elif event_type == "snapshot":
                data = ChatResponseSnapshotResponse.model_validate(
                    item["snapshot"], from_attributes=True
                ).model_dump(mode="json")
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

    except ProjectException as exc:
        payload = json.dumps(
            {
                "code": (exc.data or {}).get("code", "chat_stream_failed"),
                "message": exc.message,
            },
            ensure_ascii=False,
        )
        yield f"event: error\ndata: {payload}\n\n"
    except Exception:
        logger.exception("Research response stream failed")
        yield 'event: error\ndata: {"code":"chat_stream_failed","message":"The research response could not be completed."}\n\n'


@chat_session_router.post(
    "/{session_id}/tool-calls/{tool_call_id}/decision",
    response_model=ApiResponse[ChatTurnResponse],
    summary="Approve or reject one exact Research Agent write call",
)
async def decide_chat_tool_call(
    request: Request,
    session_id: str,
    tool_call_id: str,
    payload: ChatToolDecisionRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    turn = await request.app.state.runtime.chat_session_service.decide_tool_call_for_user(
        session_id,
        tool_call_id,
        user_id,
        arguments_digest=payload.arguments_digest,
        decision=payload.decision,
    )
    return make_api_response(data=_turn_response(turn))



def _turn_response(turn: Mapping[str, Any]) -> ChatTurnResponse:
    pending = turn.get("pending_approval")
    return ChatTurnResponse(
        status=str(turn["status"]),
        completion_reason=turn.get("completion_reason"),
        warnings=list(turn.get("warnings") or ()),
        execution_plan=turn.get("execution_plan"),
        messages=[
            ChatMessageResponse.model_validate(item, from_attributes=True)
            for item in turn.get("messages") or ()
        ],
        pending_approval=(
            ChatToolCallResponse.model_validate(pending, from_attributes=True)
            if pending is not None
            else None
        ),
        error_code=(
            str(turn["error_code"]) if turn.get("error_code") is not None else None
        ),
    )


__all__ = ["chat_session_router"]
