"""Relational storage for auditable Research Agent Chat trajectories."""

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
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class AgentTaskORM(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "trigger_message_id"],
            ["chat_messages.conversation_id", "chat_messages.message_id"],
            name="agent_tasks_trigger_message_same_session",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["task_id", "checkpoint_message_id"],
            ["chat_messages.produced_by_task_id", "chat_messages.message_id"],
            name="agent_tasks_checkpoint_message_same_task",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["task_id", "final_message_id"],
            ["chat_messages.produced_by_task_id", "chat_messages.message_id"],
            name="agent_tasks_final_message_same_task",
            use_alter=True,
        ),
        UniqueConstraint("session_id", "task_id", name="agent_tasks_session_task_unique"),
        CheckConstraint(
            "trigger_kind IN ('user_message', 'approval', 'retry', 'schedule', 'system')",
            name="chat_task_trigger_kind_valid",
        ),
        CheckConstraint(
            "status IN ('accepted', 'running', 'approval_required', 'completed', "
            "'failed', 'interrupted', 'cancelled')",
            name="chat_task_status_valid",
        ),
        CheckConstraint("checkpoint_revision >= 0", name="chat_task_checkpoint_revision_valid"),
        CheckConstraint(
            "trigger_kind NOT IN ('user_message', 'retry') OR trigger_message_id IS NOT NULL",
            name="chat_task_trigger_message_required",
        ),
        CheckConstraint(
            "(status = 'completed') = (final_message_id IS NOT NULL)",
            name="chat_task_completed_message_valid",
        ),
        CheckConstraint("updated_at >= started_at", name="chat_task_timestamps_valid"),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="chat_task_finished_at_valid",
        ),
        Index("agent_active_task_idx", "session_id", "status", "updated_at"),
    )

    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("chat_conversations.conversation_id", ondelete="CASCADE"), nullable=False
    )
    trigger_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    final_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checkpoint_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    checkpoint_revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=dict, server_default="{}"
    )
    model_connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_connection_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentOperationORM(Base):
    __tablename__ = "agent_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "assistant_message_id"],
            ["chat_messages.produced_by_task_id", "chat_messages.message_id"],
            name="chat_operation_assistant_message_same_task",
            use_alter=True,
        ),
        UniqueConstraint("task_id", "operation_id", name="chat_operation_task_operation_unique"),
        UniqueConstraint("task_id", "tool_call_id", name="chat_operation_task_tool_call_unique"),
        CheckConstraint(
            "risk IN ('read', 'draft', 'write', 'unknown')",
            name="chat_operation_risk_valid",
        ),
        CheckConstraint(
            "status IN ('requested', 'approval_required', 'approved', 'running', "
            "'succeeded', 'failed', 'rejected', 'needs_reconciliation')",
            name="chat_operation_status_valid",
        ),
        CheckConstraint(
            "length(arguments_digest) = 64",
            name="chat_operation_arguments_digest_length",
        ),
        CheckConstraint(
            "decision_arguments_digest IS NULL OR decision_arguments_digest = arguments_digest",
            name="chat_operation_decision_digest_valid",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="chat_operation_timestamps_valid",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="chat_operation_finished_at_valid",
        ),
    )

    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("agent_tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assistant_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    arguments_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_basis: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="registry"
    )
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(_JSON_DOCUMENT, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_arguments_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentTaskStepORM(Base):
    __tablename__ = "agent_task_steps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id"], ["agent_tasks.task_id"], ondelete="CASCADE",
            name="chat_task_step_task_fk",
        ),
        UniqueConstraint("task_id", "sequence", name="chat_task_step_sequence_unique"),
        CheckConstraint("sequence >= 0", name="chat_task_step_sequence_valid"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'blocked')",
            name="chat_task_step_status_valid",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="chat_task_step_finished_at_valid",
        ),
    )

    step_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatModelCallORM(Base):
    """One exact request submitted to an LLM provider."""

    __tablename__ = "chat_model_calls"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('decision', 'compaction', 'finalization')",
            name="chat_model_call_purpose_valid",
        ),
        CheckConstraint(
            "status IN ('recorded', 'provider_succeeded', 'provider_failed', "
            "'response_invalid', 'cancelled')",
            name="chat_model_call_status_valid",
        ),
        CheckConstraint("length(request_digest) = 64", name="chat_model_call_digest_length"),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="chat_model_call_timestamps_valid",
        ),
        UniqueConstraint(
            "task_id",
            "sequence",
            name="chat_model_call_task_sequence",
        ),
        ForeignKeyConstraint(
            ["session_id", "task_id"],
            ["agent_tasks.session_id", "agent_tasks.task_id"],
            name="chat_model_call_task_same_session",
            use_alter=True,
        ),
        CheckConstraint(
            "sequence IS NULL OR sequence >= 0",
            name="chat_model_call_sequence_non_negative",
        ),
    )

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger_message_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    response_message_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    model_connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)


__all__ = [
    "ChatModelCallORM",
    "AgentTaskORM",
    "AgentOperationORM",
    "AgentTaskStepORM",
]
