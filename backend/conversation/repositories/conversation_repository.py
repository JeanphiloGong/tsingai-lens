"""Persist conversations, selected message paths, and answer feedback."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import uuid4

from conversation.domain import ConversationPath, Message, Role, path_to
from domain.chat.feedback import FeedbackRating, FeedbackReason
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.chat import AgentTaskORM, ChatToolCallORM
from infra.persistence.postgres.models.collection import CollectionORM
from infra.persistence.postgres.models.conversation import (
    ConversationORM,
    MessageFeedbackORM,
    MessageORM,
)
from sqlalchemy import and_, case, delete, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import aggregate_order_by, insert
from sqlalchemy.ext.asyncio import AsyncSession


class ConversationNotFound(FileNotFoundError):
    """The conversation is absent or outside the caller's scope."""

    def __init__(self, message: str, *, code: str = "conversation_not_found") -> None:
        super().__init__(message)
        self.code = code


class ConversationPathConflict(ValueError):
    def __init__(self, current_revision: int) -> None:
        super().__init__("Conversation path revision is stale.")
        self.current_revision = current_revision


class FeedbackTargetInvalid(ValueError):
    """Feedback requires a saved assistant answer without tool requests."""


ConversationStatus = Literal["idle", "running", "approval"]


@dataclass(frozen=True)
class ConversationRecord:
    conversation_id: str
    workspace_id: str
    title: str | None
    is_pinned: bool
    current_message_id: str | None
    current_task_id: str | None
    path_revision: int
    forked_from_message_id: str | None
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime


_CONVERSATION_TASKS = (
    select(1)
    .where(
        AgentTaskORM.session_id == ConversationORM.conversation_id,
    )
    .correlate(ConversationORM)
)
_CONVERSATION_STATUS = case(
    (
        _CONVERSATION_TASKS.where(AgentTaskORM.status == "approval_required").exists(),
        "approval",
    ),
    (_CONVERSATION_TASKS.where(AgentTaskORM.status == "running").exists(), "running"),
    else_="idle",
)


def _owned_conversation(user_id: str):
    return and_(
        ConversationORM.user_id == user_id,
        select(1)
        .where(
            CollectionORM.collection_id == ConversationORM.workspace_id,
            CollectionORM.owner_user_id == user_id,
        )
        .correlate(ConversationORM)
        .exists(),
    )


def _to_record(row: ConversationORM, status: ConversationStatus) -> ConversationRecord:
    return ConversationRecord(
        conversation_id=row.conversation_id,
        workspace_id=row.workspace_id,
        title=row.title,
        is_pinned=row.is_pinned,
        current_message_id=row.current_message_id,
        current_task_id=row.current_task_id,
        path_revision=row.path_revision,
        forked_from_message_id=row.forked_from_message_id,
        status=status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@dataclass(frozen=True)
class MessageFeedbackView:
    feedback_id: str
    rating: str
    reason: str | None
    comment: str | None
    response_digest: str
    created_at: datetime
    updated_at: datetime


def _to_feedback_view(row: MessageFeedbackORM) -> MessageFeedbackView:
    return MessageFeedbackView(
        row.feedback_id,
        row.rating,
        row.reason,
        row.comment,
        row.response_digest,
        row.created_at,
        row.updated_at,
    )


@dataclass(frozen=True)
class ConversationMessageView:
    message: Message
    source_contexts: tuple[dict[str, Any], ...]
    my_feedback: MessageFeedbackView | None


@dataclass(frozen=True)
class ConversationPathView:
    conversation: ConversationRecord
    path: ConversationPath
    items: tuple[ConversationMessageView, ...]
    active_tasks: tuple[dict[str, Any], ...]


class ConversationRepository:
    async def list_conversations(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int,
        offset: int,
    ) -> tuple[ConversationRecord, ...]:
        statement = (
            select(ConversationORM, _CONVERSATION_STATUS)
            .where(
                _owned_conversation(user_id),
                ConversationORM.workspace_id == workspace_id,
            )
            .order_by(
                ConversationORM.is_pinned.desc(),
                ConversationORM.updated_at.desc(),
                ConversationORM.conversation_id,
            )
            .limit(limit)
            .offset(offset)
        )
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(statement)).all()
        return tuple(_to_record(row, status) for row, status in rows)

    async def create_conversation(
        self, *, user_id: str, workspace_id: str
    ) -> ConversationRecord:
        async with AsyncSessionLocal() as db, db.begin():
            workspace = await db.scalar(
                select(CollectionORM.collection_id)
                .where(
                    CollectionORM.collection_id == workspace_id,
                    CollectionORM.owner_user_id == user_id,
                )
                .with_for_update(read=True)
            )
            if workspace is None:
                raise ConversationNotFound(
                    "Workspace not found.", code="workspace_not_found"
                )
            now = datetime.now(UTC)
            row = ConversationORM(
                conversation_id=f"conv_{uuid4().hex}",
                workspace_id=workspace_id,
                user_id=user_id,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.flush()
            return _to_record(row, "idle")

    async def read_conversation(
        self, *, conversation_id: str, user_id: str
    ) -> ConversationRecord:
        statement = select(ConversationORM, _CONVERSATION_STATUS).where(
            ConversationORM.conversation_id == conversation_id,
            _owned_conversation(user_id),
        )
        async with AsyncSessionLocal() as db:
            record = (await db.execute(statement)).one_or_none()
        if record is None:
            raise ConversationNotFound("Conversation not found.")
        return _to_record(*record)

    async def read_current_path(
        self, *, conversation_id: str, user_id: str
    ) -> ConversationPathView:
        active_tasks = (
            select(
                func.jsonb_agg(
                    aggregate_order_by(
                        func.jsonb_build_object(
                            "task_id",
                            AgentTaskORM.task_id,
                            "status",
                            AgentTaskORM.status,
                            "checkpoint_revision",
                            AgentTaskORM.checkpoint_revision,
                        ),
                        AgentTaskORM.started_at,
                        AgentTaskORM.task_id,
                    )
                )
            )
            .where(
                AgentTaskORM.session_id == ConversationORM.conversation_id,
                AgentTaskORM.status.in_(
                    ("accepted", "running", "approval_required", "interrupted")
                ),
            )
            .correlate(ConversationORM)
            .scalar_subquery()
        )
        selection = (
            select(
                ConversationORM.conversation_id,
                _CONVERSATION_STATUS.label("status"),
                active_tasks.label("active_tasks"),
                func.coalesce(
                    ConversationORM.current_message_id,
                    AgentTaskORM.final_message_id,
                    AgentTaskORM.checkpoint_message_id,
                    AgentTaskORM.trigger_message_id,
                ).label("tip_id"),
            )
            .outerjoin(
                AgentTaskORM,
                and_(
                    AgentTaskORM.task_id == ConversationORM.current_task_id,
                    AgentTaskORM.session_id == ConversationORM.conversation_id,
                ),
            )
            .where(
                ConversationORM.conversation_id == conversation_id,
                _owned_conversation(user_id),
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
            select(
                selection.c.tip_id,
                selection.c.status,
                selection.c.active_tasks,
                ConversationORM,
                MessageORM,
                MessageFeedbackORM,
            )
            .select_from(selection)
            .join(
                ConversationORM,
                ConversationORM.conversation_id == selection.c.conversation_id,
            )
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
            raise ConversationNotFound("Conversation not found.")

        tip_id, status, tasks, conversation, _, _ = rows[0]
        items = {}
        for _, _, _, _, row, feedback in rows:
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
                my_feedback=_to_feedback_view(feedback)
                if feedback is not None
                else None,
            )
        path = path_to(
            {message_id: item.message for message_id, item in items.items()}, tip_id
        )
        return ConversationPathView(
            conversation=_to_record(conversation, status),
            path=path,
            items=tuple(items[message.message_id] for message in path.items),
            active_tasks=tuple(tasks or ()),
        )

    async def select_path(
        self,
        *,
        conversation_id: str,
        user_id: str,
        expected_path_revision: int,
        tip_message_id: str | None,
        task_id: str | None,
    ) -> ConversationRecord:
        async with AsyncSessionLocal() as db, db.begin():
            record = (
                await db.execute(
                    select(ConversationORM, _CONVERSATION_STATUS)
                    .where(
                        ConversationORM.conversation_id == conversation_id,
                        _owned_conversation(user_id),
                    )
                    .with_for_update(of=ConversationORM)
                )
            ).one_or_none()
            if record is None:
                raise ConversationNotFound("Conversation not found.")
            row, status = record
            if row.path_revision != expected_path_revision:
                raise ConversationPathConflict(row.path_revision)
            if tip_message_id is not None:
                target = await db.scalar(
                    select(MessageORM.message_id)
                    .where(
                        MessageORM.conversation_id == conversation_id,
                        MessageORM.message_id == tip_message_id,
                    )
                    .with_for_update(read=True, key_share=True)
                )
                if target is None:
                    raise ConversationNotFound(
                        "Message not found.", code="message_not_found"
                    )
            else:
                target = await db.scalar(
                    select(AgentTaskORM.task_id)
                    .where(
                        AgentTaskORM.session_id == conversation_id,
                        AgentTaskORM.task_id == task_id,
                        AgentTaskORM.status.in_(
                            ("running", "approval_required", "completed")
                        ),
                    )
                    .with_for_update(read=True)
                )
                if target is None:
                    raise ConversationNotFound("Task not found.", code="task_not_found")

            if (row.current_message_id, row.current_task_id) != (
                tip_message_id,
                task_id,
            ):
                row.current_message_id = tip_message_id
                row.current_task_id = task_id
                row.path_revision += 1
            return _to_record(row, status)

    async def update_title(
        self, *, conversation_id: str, user_id: str, title: str
    ) -> ConversationRecord:
        async with AsyncSessionLocal() as db, db.begin():
            result = (
                await db.execute(
                    update(ConversationORM)
                    .where(
                        ConversationORM.conversation_id == conversation_id,
                        _owned_conversation(user_id),
                    )
                    .values(title=title)
                    .returning(ConversationORM, _CONVERSATION_STATUS)
                )
            ).one_or_none()
            if result is None:
                raise ConversationNotFound("Conversation not found.")
            return _to_record(*result)

    async def update_pin(
        self, *, conversation_id: str, user_id: str, is_pinned: bool
    ) -> ConversationRecord:
        async with AsyncSessionLocal() as db, db.begin():
            result = (
                await db.execute(
                    update(ConversationORM)
                    .where(
                        ConversationORM.conversation_id == conversation_id,
                        _owned_conversation(user_id),
                    )
                    .values(is_pinned=is_pinned)
                    .returning(ConversationORM, _CONVERSATION_STATUS)
                )
            ).one_or_none()
            if result is None:
                raise ConversationNotFound("Conversation not found.")
            return _to_record(*result)

    async def upsert_feedback(
        self,
        *,
        conversation_id: str,
        message_id: str,
        user_id: str,
        rating: FeedbackRating,
        reason: FeedbackReason | None,
        comment: str | None,
    ) -> MessageFeedbackView:
        async with AsyncSessionLocal() as db, db.begin():
            message = await self._feedback_target(
                db, conversation_id, message_id, user_id
            )
            row = MessageFeedbackORM
            statement = insert(row).values(
                feedback_id=f"feedback_{uuid4().hex}",
                conversation_id=conversation_id,
                message_id=message_id,
                user_id=user_id,
                rating=rating,
                reason=reason,
                comment=comment,
                response_digest=sha256(message.content.encode("utf-8")).hexdigest(),
                created_at=func.now(),
                updated_at=func.now(),
            )
            submitted = statement.excluded
            saved = (
                await db.scalars(
                    statement.on_conflict_do_update(
                        constraint="uq_chat_message_feedback_user_message",
                        set_={
                            "rating": submitted.rating,
                            "reason": submitted.reason,
                            "comment": submitted.comment,
                            "response_digest": submitted.response_digest,
                            "updated_at": func.greatest(
                                row.updated_at, submitted.updated_at
                            ),
                        },
                        where=or_(
                            row.rating != submitted.rating,
                            row.reason.is_distinct_from(submitted.reason),
                            row.comment.is_distinct_from(submitted.comment),
                            row.response_digest != submitted.response_digest,
                        ),
                    ).returning(row)
                )
            ).one_or_none()
            if saved is None:
                saved = (
                    await db.scalars(
                        select(row).where(
                            row.user_id == user_id,
                            row.message_id == message_id,
                        )
                    )
                ).one()
            return _to_feedback_view(saved)

    async def delete_feedback(
        self, *, conversation_id: str, message_id: str, user_id: str
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            await self._feedback_target(db, conversation_id, message_id, user_id)
            await db.execute(
                delete(MessageFeedbackORM).where(
                    MessageFeedbackORM.conversation_id == conversation_id,
                    MessageFeedbackORM.message_id == message_id,
                    MessageFeedbackORM.user_id == user_id,
                )
            )

    async def _feedback_target(
        self,
        db: AsyncSession,
        conversation_id: str,
        message_id: str,
        user_id: str,
    ) -> MessageORM:
        target = (
            await db.execute(
                select(
                    MessageORM,
                    select(1)
                    .where(
                        ChatToolCallORM.assistant_message_id == MessageORM.message_id,
                    )
                    .correlate(MessageORM)
                    .exists(),
                )
                .join(
                    ConversationORM,
                    ConversationORM.conversation_id == MessageORM.conversation_id,
                )
                .where(
                    MessageORM.conversation_id == conversation_id,
                    MessageORM.message_id == message_id,
                    _owned_conversation(user_id),
                )
                .with_for_update(of=MessageORM, read=True)
            )
        ).one_or_none()
        if target is None:
            raise ConversationNotFound(
                "Feedback message not found.", code="feedback_message_not_found"
            )
        message, has_legacy_tool_calls = target
        if (
            message.role != "assistant"
            or not message.content
            or message.tool_requests
            or has_legacy_tool_calls
        ):
            raise FeedbackTargetInvalid(
                "Feedback requires an assistant text answer without tool requests."
            )
        return message
