"""Conversation commands that coordinate Message and Agent Task writes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4

from conversation.application.source_context import canonical_source_contexts
from domain.chat.source_context import ChatSourceContext
from agent.repositories.task_repository import TaskRepository
from conversation.repositories.conversation_repository import (
    ConversationRepository,
    ConversationWriteConflict,
)


@dataclass(frozen=True)
class AcceptedTask:
    task_id: str
    trigger_message_id: str
    status: str


class ConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        task_repository: TaskRepository,
    ) -> None:
        self.repository = repository
        self.task_repository = task_repository

    async def accept_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        parent_message_id: str | None,
        content: str,
        source_contexts: tuple[ChatSourceContext, ...],
        model_connection_id: str | None = None,
    ) -> AcceptedTask:
        async with self.repository.session() as db, db.begin():
            conversation = await self.repository.lock_owned_conversation(db, conversation_id, user_id)
            if parent_message_id is not None:
                parent = await self.repository.lock_owned_message(
                    db, conversation_id, parent_message_id, user_id
                )
                if parent.role == "tool" or not parent.content:
                    raise ConversationWriteConflict("message_parent_invalid")
            message_id = f"msg_{uuid4().hex}"
            task_id = f"task_{uuid4().hex}"
            await self.repository.insert_user_message(
                db,
                message_id=message_id,
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
                content=content,
                source_contexts=tuple(
                    asdict(item)
                    for item in await canonical_source_contexts(conversation.workspace_id, source_contexts)
                ),
            )
            await self.task_repository.insert_accepted_task(
                db,
                task_id=task_id,
                conversation_id=conversation_id,
                trigger_message_id=message_id,
                model_connection_id=model_connection_id,
            )
            await self.repository.select_new_task(db, conversation_id, task_id)
        return AcceptedTask(task_id=task_id, trigger_message_id=message_id, status="accepted")

    async def create_retry_task(
        self, *, conversation_id: str, message_id: str, user_id: str
    ) -> AcceptedTask:
        async with self.repository.session() as db, db.begin():
            await self.repository.lock_owned_conversation(db, conversation_id, user_id)
            message = await self.repository.lock_owned_message(
                db, conversation_id, message_id, user_id
            )
            if message.role != "user":
                raise ConversationWriteConflict("retry_source_invalid")
            task_id = f"task_{uuid4().hex}"
            await self.task_repository.insert_accepted_task(
                db,
                task_id=task_id,
                conversation_id=conversation_id,
                trigger_message_id=message_id,
            )
            await self.repository.select_new_task(db, conversation_id, task_id)
        return AcceptedTask(task_id=task_id, trigger_message_id=message_id, status="accepted")

    async def edit_message(
        self,
        *,
        conversation_id: str,
        message_id: str,
        user_id: str,
        content: str,
        source_contexts: tuple[ChatSourceContext, ...] | None,
    ) -> AcceptedTask:
        async with self.repository.session() as db, db.begin():
            conversation = await self.repository.lock_owned_conversation(db, conversation_id, user_id)
            original = await self.repository.lock_owned_message(
                db, conversation_id, message_id, user_id
            )
            if original.role != "user":
                raise ConversationWriteConflict("edit_source_invalid")
            if source_contexts is None:
                saved_source_contexts = tuple(
                    await self.repository.read_source_contexts(
                        db, conversation_id, message_id
                    )
                )
            else:
                saved_source_contexts = tuple(
                    asdict(item)
                    for item in await canonical_source_contexts(conversation.workspace_id, source_contexts)
                )
            edited_id = f"msg_{uuid4().hex}"
            task_id = f"task_{uuid4().hex}"
            await self.repository.insert_user_message(
                db,
                message_id=edited_id,
                conversation_id=conversation_id,
                parent_message_id=original.parent_message_id,
                content=content,
                source_contexts=saved_source_contexts,
            )
            await self.task_repository.insert_accepted_task(
                db,
                task_id=task_id,
                conversation_id=conversation_id,
                trigger_message_id=edited_id,
            )
            await self.repository.select_new_task(db, conversation_id, task_id)
        return AcceptedTask(task_id=task_id, trigger_message_id=edited_id, status="accepted")


__all__ = ["AcceptedTask", "ConversationService", "ConversationWriteConflict"]
