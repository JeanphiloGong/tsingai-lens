"""Conversation message commands."""

from __future__ import annotations

from domain.chat.source_context import ChatSourceContext
from agent.repositories.task_repository import TaskRepository
from conversation.application.conversation_service import AcceptedTask, ConversationService
from conversation.repositories.conversation_repository import ConversationRepository


class SendConversationMessage:
    """Accept one user Message and its durable Agent Task."""

    def __init__(self, service: ConversationService) -> None:
        self.service = service

    async def __call__(
        self,
        *,
        conversation_id: str,
        user_id: str,
        parent_message_id: str | None,
        content: str,
        source_contexts: tuple[ChatSourceContext, ...],
        model_connection_id: str | None = None,
    ) -> AcceptedTask:
        return await self.service.accept_message(
            conversation_id=conversation_id,
            user_id=user_id,
            parent_message_id=parent_message_id,
            content=content,
            source_contexts=source_contexts,
            model_connection_id=model_connection_id,
        )


conversation_service = ConversationService(
    repository=ConversationRepository(),
    task_repository=TaskRepository(),
)
send_conversation_message = SendConversationMessage(conversation_service)


__all__ = [
    "SendConversationMessage",
    "conversation_service",
    "send_conversation_message",
]
