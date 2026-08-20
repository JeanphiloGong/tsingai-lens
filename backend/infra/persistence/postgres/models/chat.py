"""Relational storage for auditable Research Agent Chat trajectories."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ChatSessionRow(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint("updated_at >= created_at", name="valid_timestamps"),
    )

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("auth_users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint(
            "role IN ('user', 'assistant', 'tool')",
            name="role_valid",
        ),
        UniqueConstraint("session_id", "position", name="uq_chat_messages_position"),
    )

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_arguments: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatToolCallRow(Base):
    __tablename__ = "chat_tool_calls"
    __table_args__ = (
        CheckConstraint(
            "risk IN ('unknown', 'read', 'draft', 'write')",
            name="risk_valid",
        ),
        CheckConstraint(
            "status IN ('requested', 'approval_required', 'approved', 'running', "
            "'succeeded', 'failed', 'rejected')",
            name="status_valid",
        ),
        UniqueConstraint(
            "assistant_message_id",
            name="uq_chat_tool_calls_assistant_message",
        ),
    )

    tool_call_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assistant_message_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_messages.message_id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    arguments_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision_user_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("auth_users.user_id", ondelete="RESTRICT"),
        nullable=True,
    )
    decision_arguments_digest: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ChatToolResultRow(Base):
    __tablename__ = "chat_tool_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'queued', 'failed')",
            name="status_valid",
        ),
    )

    tool_call_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_tool_calls.tool_call_id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    resource_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "ChatMessageRow",
    "ChatSessionRow",
    "ChatToolCallRow",
    "ChatToolResultRow",
]
