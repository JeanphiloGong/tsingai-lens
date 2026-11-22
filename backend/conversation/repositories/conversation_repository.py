"""Read the selected conversation path and its feedback in one snapshot."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import and_, func, select, true

from conversation.domain import ConversationPath, Message, Role, path_to
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.chat import AgentTaskORM
from infra.persistence.postgres.models.collection import CollectionORM
from infra.persistence.postgres.models.conversation import (
    ConversationORM,
    MessageFeedbackORM,
    MessageORM,
)


class ConversationNotFound(FileNotFoundError):
    """The conversation is absent or outside the caller's scope."""


@dataclass(frozen=True)
class MessageFeedbackView:
    feedback_id: str
    rating: str
    reason: str | None
    comment: str | None
    response_digest: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ConversationMessageView:
    message: Message
    source_contexts: tuple[dict[str, Any], ...]
    my_feedback: MessageFeedbackView | None


@dataclass(frozen=True)
class ConversationPathView:
    path: ConversationPath
    path_revision: int
    items: tuple[ConversationMessageView, ...]


class ConversationRepository:
    async def read_current_path(
        self, *, conversation_id: str, user_id: str
    ) -> ConversationPathView:
        selection = (
            select(
                ConversationORM.conversation_id,
                ConversationORM.path_revision,
                func.coalesce(
                    ConversationORM.current_message_id,
                    AgentTaskORM.final_message_id,
                    AgentTaskORM.checkpoint_message_id,
                    AgentTaskORM.trigger_message_id,
                ).label("tip_id"),
            )
            .join(CollectionORM, CollectionORM.collection_id == ConversationORM.workspace_id)
            .outerjoin(
                AgentTaskORM,
                and_(
                    AgentTaskORM.task_id == ConversationORM.current_task_id,
                    AgentTaskORM.session_id == ConversationORM.conversation_id,
                ),
            )
            .where(
                ConversationORM.conversation_id == conversation_id,
                ConversationORM.user_id == user_id,
                CollectionORM.owner_user_id == user_id,
            )
            .cte("selected_conversation")
        )
        path_ids = (
            select(MessageORM.message_id, MessageORM.parent_message_id)
            .join(selection, MessageORM.conversation_id == selection.c.conversation_id)
            .where(MessageORM.message_id == selection.c.tip_id)
            .cte("path_ids", recursive=True)
        )
        # UNION visits each message once. The domain can then reject a cycle.
        path_ids = path_ids.union(
            select(MessageORM.message_id, MessageORM.parent_message_id)
            .join(path_ids, MessageORM.message_id == path_ids.c.parent_message_id)
            .where(MessageORM.conversation_id == conversation_id)
        )
        statement = (
            select(selection.c.tip_id, selection.c.path_revision, MessageORM, MessageFeedbackORM)
            .select_from(selection)
            .outerjoin(path_ids, true())
            .outerjoin(MessageORM, MessageORM.message_id == path_ids.c.message_id)
            .outerjoin(
                MessageFeedbackORM,
                and_(
                    MessageFeedbackORM.conversation_id == selection.c.conversation_id,
                    MessageFeedbackORM.message_id == MessageORM.message_id,
                    MessageFeedbackORM.user_id == user_id,
                    MessageORM.role == "assistant",
                ),
            )
        )
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(statement)).all()

        if not rows:
            raise ConversationNotFound("conversation not found")

        tip_id, revision, _, _ = rows[0]
        items = {}
        for _, _, row, feedback in rows:
            if row is None:
                continue
            message = Message(
                message_id=row.message_id,
                conversation_id=row.conversation_id,
                parent_message_id=row.parent_message_id,
                role=cast(Role, row.role),
                content=row.content,
                produced_by_task_id=row.produced_by_task_id,
                copied_from_message_id=row.copied_from_message_id,
            )
            items[message.message_id] = ConversationMessageView(
                message=message,
                source_contexts=tuple(row.source_contexts),
                my_feedback=MessageFeedbackView(
                    feedback.feedback_id,
                    feedback.rating,
                    feedback.reason,
                    feedback.comment,
                    feedback.response_digest,
                    feedback.created_at,
                    feedback.updated_at,
                ) if feedback is not None else None,
            )
        path = path_to({message_id: item.message for message_id, item in items.items()}, tip_id)
        return ConversationPathView(
            path=path,
            path_revision=revision,
            items=tuple(items[message.message_id] for message in path.items),
        )
