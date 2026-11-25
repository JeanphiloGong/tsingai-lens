from typing import Annotated

from controllers.dependencies.auth import get_current_user_id
from conversation.feedback.repository import FeedbackRepository
from conversation.feedback.schemas import FeedbackRequest, MessageFeedbackResponse
from fastapi import APIRouter, Depends, Response
from utils.response import ApiResponse


feedback_router = APIRouter()
repository = FeedbackRepository()
CurrentUserId = Annotated[str, Depends(get_current_user_id)]


@feedback_router.put("/{conversation_id}/messages/{message_id}/feedback")
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


@feedback_router.delete(
    "/{conversation_id}/messages/{message_id}/feedback", status_code=204
)
async def delete_feedback(
    conversation_id: str, message_id: str, user_id: CurrentUserId
) -> Response:
    await repository.delete_feedback(
        conversation_id=conversation_id, message_id=message_id, user_id=user_id
    )
    return Response(status_code=204)
