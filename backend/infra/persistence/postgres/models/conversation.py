"""PostgreSQL mappings for conversations, messages, and answer feedback."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ConversationORM(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        CheckConstraint("updated_at >= created_at", name="valid_timestamps"),
        Index(
            "ix_chat_sessions_user_workspace_updated",
            "user_id",
            "workspace_id",
            "updated_at",
            "conversation_id",
        ),
        Index(
            "chat_conversations_visible_idx",
            "user_id",
            "workspace_id",
            "updated_at",
            "conversation_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("chat_fork_source_idx", "forked_from_message_id"),
        ForeignKeyConstraint(
            ["conversation_id", "current_message_id"],
            ["chat_messages.conversation_id", "chat_messages.message_id"],
            name="chat_current_message_same_session",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["conversation_id", "current_task_id"],
            ["agent_tasks.session_id", "agent_tasks.task_id"],
            name="chat_current_task_same_session",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["forked_from_message_id"],
            ["chat_messages.message_id"],
            name="chat_fork_source_fk",
            use_alter=True,
        ),
        CheckConstraint(
            "(CASE WHEN current_message_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN current_task_id IS NULL THEN 0 ELSE 1 END) <= 1",
            name="chat_path_selection_valid",
        ),
        CheckConstraint("path_revision >= 0", name="chat_path_revision_valid"),
    )

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workspaces.workspace_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_message_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    current_task_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    path_revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    forked_from_message_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )


class MessageORM(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'tool')",
            name="role_valid",
        ),
        UniqueConstraint(
            "conversation_id", "message_id", name="chat_message_in_session_unique"
        ),
        UniqueConstraint(
            "produced_by_task_id", "message_id", name="chat_message_task_unique"
        ),
        ForeignKeyConstraint(
            ["conversation_id", "parent_message_id"],
            ["chat_messages.conversation_id", "chat_messages.message_id"],
            name="chat_message_parent_same_session",
        ),
        CheckConstraint(
            "parent_message_id IS NULL OR parent_message_id <> message_id",
            name="chat_message_parent_not_self",
        ),
        CheckConstraint(
            "role <> 'user' OR produced_by_task_id IS NULL",
            name="chat_user_message_has_no_producer",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "produced_by_task_id"],
            ["agent_tasks.session_id", "agent_tasks.task_id"],
            name="chat_message_task_same_session",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["produced_by_task_id", "operation_id"],
            ["agent_operations.task_id", "agent_operations.operation_id"],
            name="chat_message_operation_same_task",
            use_alter=True,
        ),
        Index("chat_message_children_idx", "conversation_id", "parent_message_id"),
    )

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_contexts: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT,
        nullable=False,
        default=list,
        server_default="[]",
    )
    parent_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    produced_by_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    copied_from_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageFeedbackORM(Base):
    __tablename__ = "chat_message_feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "message_id"],
            ["chat_messages.conversation_id", "chat_messages.message_id"],
            name="chat_feedback_message_same_conversation",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "user_id", "message_id", name="uq_chat_message_feedback_user_message"
        ),
        CheckConstraint("rating IN ('helpful', 'not_helpful')", name="rating_valid"),
        CheckConstraint(
            "reason IS NULL OR (rating = 'not_helpful' AND "
            "reason IN ('incorrect', 'incomplete', 'unclear', 'other'))",
            name="reason_valid",
        ),
        CheckConstraint(
            "comment IS NULL OR length(comment) <= 2000", name="comment_length"
        ),
        CheckConstraint("length(response_digest) = 64", name="digest_length"),
        CheckConstraint("updated_at >= created_at", name="valid_timestamps"),
    )

    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_messages.message_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    rating: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
