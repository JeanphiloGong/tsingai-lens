"""Conversation commands that coordinate Message and Agent Task writes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

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


def _request_digest(
    *,
    conversation_id: str,
    trigger_message_id: str,
    content: str,
    source_contexts: tuple[dict[str, object], ...],
) -> str:
    payload = json.dumps(
        {
            "conversation_id": conversation_id,
            "trigger_message_id": trigger_message_id,
            "content": content,
            "source_contexts": source_contexts,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


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
        source_contexts: tuple[dict[str, object], ...],
    ) -> AcceptedTask:
        async with self.repository.session() as db, db.begin():
            await self.repository.lock_owned_conversation(db, conversation_id, user_id)
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
                source_contexts=source_contexts,
            )
            await self.task_repository.insert_accepted_task(
                db,
                task_id=task_id,
                conversation_id=conversation_id,
                trigger_message_id=message_id,
                request_digest=_request_digest(
                    conversation_id=conversation_id,
                    trigger_message_id=message_id,
                    content=content,
                    source_contexts=source_contexts,
                ),
            )
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
                request_digest=_request_digest(
                    conversation_id=conversation_id,
                    trigger_message_id=message_id,
                    content=message.content,
                    source_contexts=(),
                ),
            )
        return AcceptedTask(task_id=task_id, trigger_message_id=message_id, status="accepted")

    async def edit_message(
        self,
        *,
        conversation_id: str,
        message_id: str,
        user_id: str,
        content: str,
        source_contexts: tuple[dict[str, object], ...] | None,
    ) -> AcceptedTask:
        async with self.repository.session() as db, db.begin():
            await self.repository.lock_owned_conversation(db, conversation_id, user_id)
            original = await self.repository.lock_owned_message(
                db, conversation_id, message_id, user_id
            )
            if original.role != "user":
                raise ConversationWriteConflict("edit_source_invalid")
            if source_contexts is None:
                source_contexts = tuple(
                    await self.repository.read_source_contexts(
                        db, conversation_id, message_id
                    )
                )
            edited_id = f"msg_{uuid4().hex}"
            task_id = f"task_{uuid4().hex}"
            await self.repository.insert_user_message(
                db,
                message_id=edited_id,
                conversation_id=conversation_id,
                parent_message_id=original.parent_message_id,
                content=content,
                source_contexts=source_contexts,
            )
            await self.task_repository.insert_accepted_task(
                db,
                task_id=task_id,
                conversation_id=conversation_id,
                trigger_message_id=edited_id,
                request_digest=_request_digest(
                    conversation_id=conversation_id,
                    trigger_message_id=edited_id,
                    content=content,
                    source_contexts=source_contexts,
                ),
            )
        return AcceptedTask(task_id=task_id, trigger_message_id=edited_id, status="accepted")


__all__ = ["AcceptedTask", "ConversationService", "ConversationWriteConflict"]
