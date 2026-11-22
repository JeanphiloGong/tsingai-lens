from typing import Annotated

from controllers.dependencies.auth import get_current_user_id
from conversation.controllers.schemas import (
    ActivePathRequest,
    ActiveTaskResponse,
    ConversationInputError,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationPinRequest,
    ConversationResponse,
    ConversationTitleRequest,
    CreateConversationRequest,
    FeedbackRequest,
    MessageFeedbackResponse,
    MessageResponse,
)
from conversation.repositories.conversation_repository import (
    ConversationNotFound,
    ConversationPathConflict,
    ConversationRepository,
    FeedbackTargetInvalid,
)
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from utils.response import ApiResponse

conversation_router = APIRouter(prefix="/conversations", tags=["conversations"])
repository = ConversationRepository()
CurrentUserId = Annotated[str, Depends(get_current_user_id)]


async def conversation_error_handler(
    _request: Request,
    exc: ConversationNotFound
    | ConversationPathConflict
    | FeedbackTargetInvalid
    | ConversationInputError,
) -> JSONResponse:
    meta: dict[str, str | int]
    if isinstance(exc, ConversationPathConflict):
        status = 409
        meta = {
            "error_code": "conversation_path_conflict",
            "current_path_revision": exc.current_revision,
        }
    elif isinstance(exc, ConversationNotFound):
        status = 404
        meta = {"error_code": exc.code}
    elif isinstance(exc, FeedbackTargetInvalid):
        status = 422
        meta = {"error_code": "feedback_message_not_assistant"}
    else:
        status = 422
        meta = {"error_code": exc.code}
    return JSONResponse(
        status_code=status,
        content={"code": status, "message": str(exc), "data": None, "meta": meta},
    )


@conversation_router.get("")
async def list_conversations(
    user_id: CurrentUserId,
    workspace_id: Annotated[str, Query(min_length=1, max_length=64)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[ConversationListResponse]:
    items = await repository.list_conversations(
        user_id=user_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
    )
    return ApiResponse(
        data=ConversationListResponse(
            items=[ConversationResponse.model_validate(item) for item in items],
            limit=limit,
            offset=offset,
        )
    )


@conversation_router.post("", status_code=201)
async def create_conversation(
    payload: CreateConversationRequest,
    user_id: CurrentUserId,
) -> ApiResponse[ConversationResponse]:
    item = await repository.create_conversation(
        user_id=user_id, workspace_id=payload.workspace_id
    )
    return ApiResponse(data=ConversationResponse.model_validate(item))


@conversation_router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str, user_id: CurrentUserId
) -> ApiResponse[ConversationResponse]:
    item = await repository.read_conversation(
        conversation_id=conversation_id, user_id=user_id
    )
    return ApiResponse(data=ConversationResponse.model_validate(item))


@conversation_router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: str, user_id: CurrentUserId
) -> ApiResponse[ConversationMessagesResponse]:
    result = await repository.read_current_path(
        conversation_id=conversation_id, user_id=user_id
    )
    return ApiResponse(
        data=ConversationMessagesResponse(
            conversation=ConversationResponse.model_validate(result.conversation),
            tip_message_id=result.path.tip_message_id,
            items=[
                MessageResponse(
                    message_id=item.message.message_id,
                    role=item.message.role,
                    content=item.message.content,
                    source_contexts=item.source_contexts,
                    my_feedback=MessageFeedbackResponse.model_validate(item.my_feedback)
                    if item.my_feedback is not None
                    else None,
                )
                for item in result.items
            ],
            active_tasks=[
                ActiveTaskResponse.model_validate(task) for task in result.active_tasks
            ],
        )
    )


@conversation_router.put("/{conversation_id}/active-path")
async def select_path(
    conversation_id: str,
    payload: ActivePathRequest,
    user_id: CurrentUserId,
) -> ApiResponse[ConversationResponse]:
    item = await repository.select_path(
        conversation_id=conversation_id,
        user_id=user_id,
        expected_path_revision=payload.expected_path_revision,
        tip_message_id=payload.tip_message_id,
        task_id=payload.task_id,
    )
    return ApiResponse(data=ConversationResponse.model_validate(item))


@conversation_router.put("/{conversation_id}/title")
async def update_title(
    conversation_id: str,
    payload: ConversationTitleRequest,
    user_id: CurrentUserId,
) -> ApiResponse[ConversationResponse]:
    item = await repository.update_title(
        conversation_id=conversation_id,
        user_id=user_id,
        title=payload.title,
    )
    return ApiResponse(data=ConversationResponse.model_validate(item))


@conversation_router.put("/{conversation_id}/pin")
async def update_pin(
    conversation_id: str,
    payload: ConversationPinRequest,
    user_id: CurrentUserId,
) -> ApiResponse[ConversationResponse]:
    item = await repository.update_pin(
        conversation_id=conversation_id,
        user_id=user_id,
        is_pinned=payload.is_pinned,
    )
    return ApiResponse(data=ConversationResponse.model_validate(item))


@conversation_router.put("/{conversation_id}/messages/{message_id}/feedback")
async def upsert_feedback(
    conversation_id: str,
    message_id: str,
    payload: FeedbackRequest,
    user_id: CurrentUserId,
) -> ApiResponse[MessageFeedbackResponse]:
    item = await repository.upsert_feedback(
        conversation_id=conversation_id,
        message_id=message_id,
        user_id=user_id,
        rating=payload.rating,
        reason=payload.reason,
        comment=payload.comment,
    )
    return ApiResponse(data=MessageFeedbackResponse.model_validate(item))


@conversation_router.delete(
    "/{conversation_id}/messages/{message_id}/feedback", status_code=204
)
async def delete_feedback(
    conversation_id: str, message_id: str, user_id: CurrentUserId
) -> Response:
    await repository.delete_feedback(
        conversation_id=conversation_id, message_id=message_id, user_id=user_id
    )
    return Response(status_code=204)
