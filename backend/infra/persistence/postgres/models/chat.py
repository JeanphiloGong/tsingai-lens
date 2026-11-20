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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ChatSessionORM(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint("updated_at >= created_at", name="valid_timestamps"),
        Index(
            "ix_chat_sessions_user_collection_updated",
            "user_id",
            "collection_id",
            "updated_at",
            "session_id",
        ),
        Index(
            "chat_fork_request_unique",
            "user_id",
            "fork_request_id",
            unique=True,
            postgresql_where=text("fork_request_id IS NOT NULL"),
        ),
        Index("chat_fork_source_idx", "forked_from_message_id"),
        ForeignKeyConstraint(
            ["session_id", "current_message_id"],
            ["chat_messages.session_id", "chat_messages.message_id"],
            name="chat_current_message_same_session",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["session_id", "current_task_id"],
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

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_session_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    parent_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fork_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fork_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fork_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    operation_permission: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
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
    fork_request_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), nullable=True
    )


class ChatMessageORM(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint(
            "role IN ('user', 'assistant', 'tool')",
            name="role_valid",
        ),
        UniqueConstraint("session_id", "position", name="uq_chat_messages_position"),
        UniqueConstraint(
            "session_id", "message_id", name="chat_message_in_session_unique"
        ),
        UniqueConstraint(
            "produced_by_task_id", "message_id", name="chat_message_task_unique"
        ),
        ForeignKeyConstraint(
            ["session_id", "parent_message_id"],
            ["chat_messages.session_id", "chat_messages.message_id"],
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
            ["session_id", "produced_by_task_id"],
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
        Index("ix_chat_messages_session_role_position", "session_id", "role", "position"),
        Index("chat_message_children_idx", "session_id", "parent_message_id"),
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
    tool_requests: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    tool_result: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatMessageFeedbackORM(Base):
    __tablename__ = "chat_message_feedback"
    __table_args__ = (
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
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
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


class ChatToolCallORM(Base):
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
            "position",
            name="uq_chat_tool_calls_assistant_position",
        ),
        CheckConstraint("position >= 0", name="position_non_negative"),
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
    position: Mapped[int] = mapped_column(Integer, nullable=False)
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
        nullable=True,
    )
    decision_arguments_digest: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision_basis: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="explicit"
    )
    authorization_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposed_permission_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    result_data: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    result_resource_refs: Mapped[list[dict[str, Any]] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    result_warnings: Mapped[list[str] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    result_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentTaskORM(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "trigger_message_id"],
            ["chat_messages.session_id", "chat_messages.message_id"],
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
        UniqueConstraint("session_id", "request_id", name="agent_tasks_request_unique"),
        CheckConstraint(
            "trigger_kind IN ('user_message', 'approval', 'retry', 'schedule', 'system')",
            name="chat_task_trigger_kind_valid",
        ),
        CheckConstraint(
            "status IN ('accepted', 'running', 'approval_required', 'completed', "
            "'failed', 'interrupted', 'cancelled')",
            name="chat_task_status_valid",
        ),
        CheckConstraint("length(request_digest) = 64", name="chat_task_digest_length"),
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
        String(128), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    trigger_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    final_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checkpoint_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
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
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
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
    "ChatMessageFeedbackORM",
    "ChatMessageORM",
    "ChatSessionORM",
    "ChatToolCallORM",
    "AgentTaskORM",
    "AgentOperationORM",
    "AgentTaskStepORM",
]
