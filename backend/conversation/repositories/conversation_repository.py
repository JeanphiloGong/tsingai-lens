"""Persist conversations, selected message paths, and answer feedback."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import uuid4

from conversation.domain import ConversationPath, Message, Role, path_to
from domain.chat.feedback import FeedbackRating, FeedbackReason
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.chat import (
    AgentOperationORM,
    AgentTaskORM,
    ChatToolCallORM,
)
from infra.persistence.postgres.models.collection import CollectionORM
from infra.persistence.postgres.models.conversation import (
    ConversationORM,
    MessageFeedbackORM,
    MessageORM,
)
from sqlalchemy import and_, case, delete, func, or_, select, text, true, update
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


class ConversationWriteConflict(ValueError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


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


def _owned_conversation(user_id: str, *, include_deleted: bool = False):
    conditions = [
        ConversationORM.user_id == user_id,
        select(1)
        .where(
            CollectionORM.collection_id == ConversationORM.workspace_id,
            CollectionORM.owner_user_id == user_id,
        )
        .correlate(ConversationORM)
        .exists(),
    ]
    if not include_deleted:
        conditions.append(ConversationORM.deleted_at.is_(None))
    return and_(*conditions)


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


def _message_path(messages: dict[str, Message], tip_id: str | None) -> tuple[str, ...]:
    path: list[str] = []
    seen: set[str] = set()
    while tip_id is not None:
        if tip_id in seen or tip_id not in messages:
            raise ConversationNotFound("Message tree is missing or cyclic.", code="tree_message_not_found")
        seen.add(tip_id)
        path.append(tip_id)
        tip_id = messages[tip_id].parent_message_id
    path.reverse()
    return tuple(path)


@dataclass(frozen=True)
class ConversationMessageView:
    message: Message
    created_at: datetime
    source_contexts: tuple[dict[str, Any], ...]
    my_feedback: MessageFeedbackView | None


@dataclass(frozen=True)
class ConversationPathView:
    conversation: ConversationRecord
    path: ConversationPath
    items: tuple[ConversationMessageView, ...]
    active_tasks: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class TreeNode:
    node_id: str
    kind: Literal["message", "task", "conversation"]
    parent_node_id: str | None
    edge_kind: str | None
    conversation_id: str
    message_id: str | None
    task_id: str | None
    preview: str
    forked_from_message_id: str | None = None
    deleted_source: bool = False


@dataclass(frozen=True)
class ConversationTree:
    root_conversation_id: str
    active_path: tuple[str, ...]
    nodes: tuple[TreeNode, ...]


class ConversationRepository:
    def session(self):
        return AsyncSessionLocal()

    async def lock_owned_conversation(
        self, db: AsyncSession, conversation_id: str, user_id: str
    ) -> ConversationORM:
        row = await db.scalar(
            select(ConversationORM)
            .where(
                ConversationORM.conversation_id == conversation_id,
                _owned_conversation(user_id),
            )
            .with_for_update()
        )
        if row is None:
            raise ConversationNotFound("Conversation not found.")
        return row

    async def lock_owned_message(
        self,
        db: AsyncSession,
        conversation_id: str,
        message_id: str,
        user_id: str,
    ) -> Message:
        row = await db.scalar(
            select(MessageORM)
            .join(
                ConversationORM,
                ConversationORM.conversation_id == MessageORM.conversation_id,
            )
            .where(
                MessageORM.conversation_id == conversation_id,
                MessageORM.message_id == message_id,
                _owned_conversation(user_id),
            )
            .with_for_update()
        )
        if row is None:
            raise ConversationNotFound("Message not found.", code="message_not_found")
        return Message(
            message_id=row.message_id,
            conversation_id=row.conversation_id,
            parent_message_id=row.parent_message_id,
            role=cast(Role, row.role),
            content=row.content,
            produced_by_task_id=row.produced_by_task_id,
            copied_from_message_id=row.copied_from_message_id,
        )

    async def read_source_contexts(
        self, db: AsyncSession, conversation_id: str, message_id: str
    ) -> list[dict[str, object]]:
        source_contexts = await db.scalar(
            select(MessageORM.source_contexts).where(
                MessageORM.conversation_id == conversation_id,
                MessageORM.message_id == message_id,
            )
        )
        if source_contexts is None:
            raise ConversationNotFound("Message not found.", code="message_not_found")
        return list(source_contexts)

    async def insert_user_message(
        self,
        db: AsyncSession,
        *,
        message_id: str,
        conversation_id: str,
        parent_message_id: str | None,
        content: str,
        source_contexts: tuple[dict[str, object], ...],
    ) -> None:
        next_position = await db.scalar(
            select(func.coalesce(func.max(MessageORM.position) + 1, 0)).where(
                MessageORM.conversation_id == conversation_id
            )
        )
        db.add(
            MessageORM(
                message_id=message_id,
                conversation_id=conversation_id,
                position=next_position,
                parent_message_id=parent_message_id,
                role="user",
                content=content,
                source_contexts=list(source_contexts),
                created_at=datetime.now(UTC),
            )
        )
        await db.flush()

    async def select_new_task(
        self, db: AsyncSession, conversation_id: str, task_id: str
    ) -> None:
        # The acceptance transaction holds the Conversation lock. Insert the
        # Task before setting the Conversation's foreign key to it.
        await db.flush()
        await db.execute(
            update(ConversationORM)
            .where(ConversationORM.conversation_id == conversation_id)
            .values(
                current_message_id=None,
                current_task_id=task_id,
                path_revision=ConversationORM.path_revision + 1,
                updated_at=datetime.now(UTC),
            )
        )

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

    async def delete_conversation(
        self, *, conversation_id: str, user_id: str
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            conversation = await db.scalar(
                select(ConversationORM)
                .where(
                    ConversationORM.conversation_id == conversation_id,
                    _owned_conversation(user_id, include_deleted=True),
                )
                .with_for_update()
            )
            if conversation is None:
                raise ConversationNotFound("Conversation not found.")
            if conversation.deleted_at is not None:
                return

            tasks = (
                await db.scalars(
                    select(AgentTaskORM)
                    .where(AgentTaskORM.session_id == conversation_id)
                    .with_for_update()
                )
            ).all()
            task_ids = tuple(task.task_id for task in tasks)
            now = datetime.now(UTC)
            for task in tasks:
                if task.status in {
                    "accepted",
                    "running",
                    "approval_required",
                    "interrupted",
                }:
                    task.status = "cancelled"
                    task.finished_at = task.finished_at or now
                    task.updated_at = now

            if task_ids:
                operations = (
                    await db.scalars(
                        select(AgentOperationORM)
                        .where(AgentOperationORM.task_id.in_(task_ids))
                        .with_for_update()
                    )
                ).all()
                for operation in operations:
                    if operation.status in {
                        "requested",
                        "approval_required",
                        "approved",
                    }:
                        operation.status = "rejected"
                        operation.error_code = "conversation_deleted"
                        operation.error_message = "The Conversation was deleted."
                    elif operation.status == "running":
                        operation.status = "needs_reconciliation"
                        operation.error_code = "conversation_deleted_during_execution"
                        operation.error_message = (
                            "The Conversation was deleted during execution."
                        )
                    else:
                        continue
                    operation.updated_at = now

            conversation.deleted_at = now
            conversation.updated_at = now

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
                created_at=row.created_at,
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

    async def read_tree(
        self, *, conversation_id: str, user_id: str
    ) -> ConversationTree:
        async with AsyncSessionLocal() as db:
            requested = await db.scalar(
                select(ConversationORM).where(
                    ConversationORM.conversation_id == conversation_id,
                    _owned_conversation(user_id),
                )
            )
            if requested is None:
                raise ConversationNotFound("Conversation not found.")
            conversations = (
                await db.scalars(
                    select(ConversationORM)
                    .where(
                        _owned_conversation(user_id, include_deleted=True),
                        ConversationORM.workspace_id == requested.workspace_id,
                    )
                    .order_by(
                        ConversationORM.created_at,
                        ConversationORM.conversation_id,
                    )
                )
            ).all()
            conversation_ids = tuple(item.conversation_id for item in conversations)
            active_conversation_ids = tuple(
                item.conversation_id
                for item in conversations
                if item.deleted_at is None
            )
            messages = (
                await db.scalars(
                    select(MessageORM).where(
                        MessageORM.conversation_id.in_(conversation_ids)
                    )
                )
            ).all()
            tasks = (
                await db.scalars(
                    select(AgentTaskORM)
                    .where(
                        AgentTaskORM.session_id.in_(active_conversation_ids),
                        or_(
                            AgentTaskORM.status.in_(
                                (
                                    "accepted",
                                    "running",
                                    "approval_required",
                                    "interrupted",
                                )
                            ),
                            AgentTaskORM.task_id == requested.current_task_id,
                        ),
                    )
                    .order_by(AgentTaskORM.updated_at, AgentTaskORM.task_id)
                )
            ).all()

        message_by_id = {item.message_id: item for item in messages}
        source_conversation: dict[str, str] = {}
        children_by_conversation: dict[str, list[str]] = {}
        for item in conversations:
            source = message_by_id.get(item.forked_from_message_id)
            if source is None:
                continue
            source_conversation[item.conversation_id] = source.conversation_id
            children_by_conversation.setdefault(source.conversation_id, []).append(
                item.conversation_id
            )

        root_id = requested.conversation_id
        seen_conversations: set[str] = set()
        while root_id in source_conversation and root_id not in seen_conversations:
            seen_conversations.add(root_id)
            root_id = source_conversation[root_id]

        reachable = {root_id}
        pending = [root_id]
        while pending:
            parent_id = pending.pop()
            for child_id in children_by_conversation.get(parent_id, ()):
                if child_id not in reachable:
                    reachable.add(child_id)
                    pending.append(child_id)

        messages_by_id = {
            item.message_id: Message(
                message_id=item.message_id,
                conversation_id=item.conversation_id,
                parent_message_id=item.parent_message_id,
                role=cast(Role, item.role),
                content=item.content,
                produced_by_task_id=item.produced_by_task_id,
                copied_from_message_id=item.copied_from_message_id,
            )
            for item in messages
            if item.conversation_id in reachable
        }
        nodes: list[TreeNode] = []
        conversation_by_id = {
            item.conversation_id: item for item in conversations
        }
        for item in conversations:
            if item.conversation_id not in reachable:
                continue
            if item.deleted_at is not None:
                nodes.append(
                    TreeNode(
                        node_id=f"conversation:{item.conversation_id}",
                        kind="conversation",
                        parent_node_id=None,
                        edge_kind="fork_deleted_source",
                        conversation_id=item.conversation_id,
                        message_id=None,
                        task_id=None,
                        preview="已删除的 Conversation",
                        deleted_source=True,
                    )
                )
                continue
            source = message_by_id.get(item.forked_from_message_id)
            source_conversation = (
                conversation_by_id.get(source.conversation_id)
                if source is not None
                else None
            )
            source_is_deleted = (
                source_conversation is not None
                and source_conversation.deleted_at is not None
            )
            nodes.append(
                TreeNode(
                    node_id=f"conversation:{item.conversation_id}",
                    kind="conversation",
                    parent_node_id=(
                        f"conversation:{source.conversation_id}"
                        if source_is_deleted and source is not None
                        else f"message:{source.message_id}"
                        if source is not None
                        else None
                    ),
                    edge_kind=(
                        "fork_deleted_source"
                        if source_is_deleted
                        else "fork"
                        if source is not None
                        else None
                    ),
                    conversation_id=item.conversation_id,
                    message_id=None,
                    task_id=None,
                    preview=item.title or item.conversation_id,
                    forked_from_message_id=item.forked_from_message_id,
                )
            )

        for item in messages:
            if (
                item.conversation_id not in reachable
                or conversation_by_id[item.conversation_id].deleted_at is not None
            ):
                continue
            nodes.append(
                TreeNode(
                    node_id=f"message:{item.message_id}",
                    kind="message",
                    parent_node_id=(
                        f"message:{item.parent_message_id}"
                        if item.parent_message_id
                        else f"conversation:{item.conversation_id}"
                    ),
                    edge_kind="parent" if item.parent_message_id else "conversation",
                    conversation_id=item.conversation_id,
                    message_id=item.message_id,
                    task_id=item.produced_by_task_id,
                    preview=item.content[:240],
                )
            )

        for item in tasks:
            if item.session_id not in reachable:
                continue
            nodes.append(
                TreeNode(
                    node_id=f"task:{item.task_id}",
                    kind="task",
                    parent_node_id=(
                        f"message:{item.trigger_message_id}"
                        if item.trigger_message_id
                        else f"conversation:{item.session_id}"
                    ),
                    edge_kind="task",
                    conversation_id=item.session_id,
                    message_id=None,
                    task_id=item.task_id,
                    preview=item.status,
                )
            )

        task_by_id = {item.task_id: item for item in tasks}
        selected_task = task_by_id.get(requested.current_task_id)
        selected_message_id = requested.current_message_id
        if selected_task is not None:
            selected_message_id = (
                selected_task.final_message_id
                or selected_task.checkpoint_message_id
                or selected_task.trigger_message_id
            )
        selected = _message_path(messages_by_id, selected_message_id)
        active_path = [f"conversation:{requested.conversation_id}"]
        active_path.extend(f"message:{message_id}" for message_id in selected)
        if selected_task is not None and selected_message_id == selected_task.trigger_message_id:
            active_path.append(f"task:{selected_task.task_id}")
        return ConversationTree(
            root_conversation_id=root_id,
            active_path=tuple(active_path),
            nodes=tuple(nodes),
        )

    async def _read_path_for_fork(
        self, db: AsyncSession, conversation_id: str, message_id: str
    ) -> tuple[ConversationPath, dict[str, list[dict[str, Any]]]]:
        rows = (
            await db.execute(
                text(
                    """
                    WITH RECURSIVE path AS (
                        SELECT message_id, conversation_id, parent_message_id,
                               role, content, source_contexts, produced_by_task_id
                        FROM chat_messages
                        WHERE conversation_id = :conversation_id
                          AND message_id = :message_id
                        UNION
                        SELECT parent.message_id, parent.conversation_id,
                               parent.parent_message_id, parent.role, parent.content,
                               parent.source_contexts, parent.produced_by_task_id
                        FROM chat_messages AS parent
                        JOIN path AS child
                          ON child.parent_message_id = parent.message_id
                         AND child.conversation_id = parent.conversation_id
                    )
                    SELECT message_id, conversation_id, parent_message_id,
                           role, content, source_contexts, produced_by_task_id
                    FROM path
                    """
                ),
                {"conversation_id": conversation_id, "message_id": message_id},
            )
        ).mappings().all()
        messages = {
            row["message_id"]: Message(
                message_id=row["message_id"],
                conversation_id=row["conversation_id"],
                parent_message_id=row["parent_message_id"],
                role=cast(Role, row["role"]),
                content=row["content"],
                produced_by_task_id=row["produced_by_task_id"],
            )
            for row in rows
        }
        source_contexts = {
            row["message_id"]: list(row["source_contexts"] or []) for row in rows
        }
        return path_to(messages, message_id), source_contexts

    async def _require_path_operations_terminal(
        self, db: AsyncSession, path: ConversationPath
    ) -> None:
        task_ids = {
            item.produced_by_task_id
            for item in path.items
            if item.produced_by_task_id is not None
        }
        if not task_ids:
            return
        pending = await db.scalar(
            select(func.count())
            .select_from(AgentOperationORM)
            .where(
                AgentOperationORM.task_id.in_(task_ids),
                AgentOperationORM.status.in_(
                    ("requested", "approval_required", "approved", "running")
                ),
            )
        )
        if pending:
            raise ConversationWriteConflict("fork_source_not_ready")

    async def fork_conversation(
        self, *, conversation_id: str, message_id: str, user_id: str
    ) -> ConversationRecord:
        async with AsyncSessionLocal() as db, db.begin():
            owner = await self.lock_owned_conversation(db, conversation_id, user_id)
            source = await self.lock_owned_message(
                db, conversation_id, message_id, user_id
            )
            if source.role == "tool" or (
                source.role == "assistant" and not source.content
            ):
                raise ConversationWriteConflict("fork_source_invalid")
            path, source_contexts = await self._read_path_for_fork(
                db, conversation_id, message_id
            )
            await self._require_path_operations_terminal(db, path)

            new_conversation_id = f"conv_{uuid4().hex}"
            now = datetime.now(UTC)
            title = f"{owner.title} · 分支" if owner.title else None
            fork = ConversationORM(
                conversation_id=new_conversation_id,
                user_id=user_id,
                workspace_id=owner.workspace_id,
                title=title,
                forked_from_message_id=source.message_id,
                path_revision=0,
                created_at=now,
                updated_at=now,
            )
            db.add(fork)
            await db.flush()

            copied_ids: dict[str, str] = {}
            for position, original in enumerate(path.items):
                copied_ids[original.message_id] = f"msg_{uuid4().hex}"
                db.add(
                    MessageORM(
                        message_id=copied_ids[original.message_id],
                        conversation_id=new_conversation_id,
                        position=position,
                        parent_message_id=(
                            copied_ids.get(original.parent_message_id)
                            if original.parent_message_id
                            else None
                        ),
                        role=original.role,
                        content=original.content,
                        copied_from_message_id=original.message_id,
                        source_contexts=source_contexts[original.message_id],
                        tool_requests=[],
                        tool_result=None,
                        created_at=now,
                    )
                )
            await db.flush()
            fork.current_message_id = copied_ids[source.message_id]
            fork.updated_at = now
            return _to_record(fork, "idle")

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
