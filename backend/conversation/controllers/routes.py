import logging
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
    ConversationTreeResponse,
    ConversationTitleRequest,
    CreateConversationRequest,
    EditMessageRequest,
    FeedbackRequest,
    ForkRequest,
    MessageFeedbackResponse,
    MessageResponse,
    RegenerateMessageRequest,
    SendMessageRequest,
    TaskAcceptedResponse,
    TreeNodeResponse,
)
from conversation.application.conversation_service import ConversationService
from conversation.repositories.conversation_repository import (
    ConversationNotFound,
    ConversationPathConflict,
    ConversationRepository,
    ConversationWriteConflict,
    FeedbackTargetInvalid,
)
from agent.repositories.task_repository import TaskRepository
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from utils.response import ApiResponse

conversation_router = APIRouter(prefix="/conversations", tags=["conversations"])
repository = ConversationRepository()
service = ConversationService(repository, TaskRepository())
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
logger = logging.getLogger(__name__)


async def conversation_error_handler(
    _request: Request,
    exc: ConversationNotFound
    | ConversationPathConflict
    | ConversationWriteConflict
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
    elif isinstance(exc, ConversationWriteConflict):
        status = 409 if exc.code == "fork_source_not_ready" else 422
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


@conversation_router.get("/{conversation_id}/tree")
async def get_tree(
    conversation_id: str, user_id: CurrentUserId
) -> ApiResponse[ConversationTreeResponse]:
    tree = await repository.read_tree(conversation_id=conversation_id, user_id=user_id)
    return ApiResponse(
        data=ConversationTreeResponse(
            root_conversation_id=tree.root_conversation_id,
            active_path=list(tree.active_path),
            nodes=[TreeNodeResponse.model_validate(node) for node in tree.nodes],
        )
    )


@conversation_router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    user_id: CurrentUserId,
) -> ApiResponse[TaskAcceptedResponse]:
    logger.info(
        "conversation message requested",
        extra={"request_id": str(payload.request_id) if payload.request_id else None},
    )
    accepted = await service.accept_message(
        conversation_id=conversation_id,
        user_id=user_id,
        parent_message_id=payload.parent_message_id,
        content=payload.message,
        source_contexts=tuple(payload.source_contexts),
    )
    return ApiResponse(data=TaskAcceptedResponse.model_validate(accepted))


@conversation_router.post("/{conversation_id}/messages/{message_id}/edits")
async def edit_message(
    conversation_id: str,
    message_id: str,
    payload: EditMessageRequest,
    user_id: CurrentUserId,
) -> ApiResponse[TaskAcceptedResponse]:
    logger.info(
        "conversation message edit requested",
        extra={"request_id": str(payload.request_id) if payload.request_id else None},
    )
    accepted = await service.edit_message(
        conversation_id=conversation_id,
        message_id=message_id,
        user_id=user_id,
        content=payload.message,
        source_contexts=(
            tuple(payload.source_contexts)
            if payload.source_contexts is not None
            else None
        ),
    )
    return ApiResponse(data=TaskAcceptedResponse.model_validate(accepted))


@conversation_router.post("/{conversation_id}/messages/{message_id}/regenerations")
async def regenerate_message(
    conversation_id: str,
    message_id: str,
    payload: RegenerateMessageRequest,
    user_id: CurrentUserId,
) -> ApiResponse[TaskAcceptedResponse]:
    logger.info(
        "conversation message regeneration requested",
        extra={"request_id": str(payload.request_id) if payload.request_id else None},
    )
    accepted = await service.create_retry_task(
        conversation_id=conversation_id,
        message_id=message_id,
        user_id=user_id,
    )
    return ApiResponse(data=TaskAcceptedResponse.model_validate(accepted))


@conversation_router.post("/{conversation_id}/forks")
async def fork_conversation(
    conversation_id: str,
    payload: ForkRequest,
    user_id: CurrentUserId,
) -> ApiResponse[ConversationResponse]:
    result = await repository.fork_conversation(
        conversation_id=conversation_id,
        message_id=payload.message_id,
        user_id=user_id,
    )
    return ApiResponse(data=ConversationResponse.model_validate(result))


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
