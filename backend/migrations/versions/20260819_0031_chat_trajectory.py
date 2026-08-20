"""Add independent Chat trajectory persistence.

Revision ID: 20260819_0031
Revises: 20260814_0030
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260819_0031"
down_revision: str | Sequence[str] | None = "20260814_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()),
    "postgresql",
)


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name=op.f("ck_chat_sessions_valid_timestamps"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_chat_sessions_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth_users.user_id"],
            name=op.f("fk_chat_sessions_user_id_auth_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_chat_sessions")),
    )
    op.create_index(
        op.f("ix_chat_sessions_collection_id"),
        "chat_sessions",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_sessions_user_id"),
        "chat_sessions",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "chat_messages",
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("tool_arguments", _JSON_DOCUMENT, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_chat_messages_position_non_negative"),
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'tool')",
            name=op.f("ck_chat_messages_role_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.session_id"],
            name=op.f("fk_chat_messages_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_chat_messages")),
        sa.UniqueConstraint(
            "session_id",
            "position",
            name="uq_chat_messages_position",
        ),
    )
    op.create_index(
        op.f("ix_chat_messages_session_id"),
        "chat_messages",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "chat_tool_calls",
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("assistant_message_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("arguments", _JSON_DOCUMENT, nullable=False),
        sa.Column("arguments_digest", sa.String(length=64), nullable=False),
        sa.Column("risk", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("decision_user_id", sa.String(length=64), nullable=True),
        sa.Column(
            "decision_arguments_digest",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "risk IN ('unknown', 'read', 'draft', 'write')",
            name=op.f("ck_chat_tool_calls_risk_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'approval_required', 'approved', 'running', "
            "'succeeded', 'failed', 'rejected')",
            name=op.f("ck_chat_tool_calls_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"],
            ["chat_messages.message_id"],
            name=op.f("fk_chat_tool_calls_assistant_message_id_chat_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decision_user_id"],
            ["auth_users.user_id"],
            name=op.f("fk_chat_tool_calls_decision_user_id_auth_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.session_id"],
            name=op.f("fk_chat_tool_calls_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tool_call_id", name=op.f("pk_chat_tool_calls")),
        sa.UniqueConstraint(
            "assistant_message_id",
            name="uq_chat_tool_calls_assistant_message",
        ),
    )
    op.create_index(
        op.f("ix_chat_tool_calls_session_id"),
        "chat_tool_calls",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "chat_tool_results",
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("data", _JSON_DOCUMENT, nullable=False),
        sa.Column("resource_refs", _JSON_DOCUMENT, nullable=False),
        sa.Column("warnings", _JSON_DOCUMENT, nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('succeeded', 'queued', 'failed')",
            name=op.f("ck_chat_tool_results_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id"],
            ["chat_tool_calls.tool_call_id"],
            name=op.f("fk_chat_tool_results_tool_call_id_chat_tool_calls"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tool_call_id", name=op.f("pk_chat_tool_results")),
    )


def downgrade() -> None:
    op.drop_table("chat_tool_results")
    op.drop_index(op.f("ix_chat_tool_calls_session_id"), table_name="chat_tool_calls")
    op.drop_table("chat_tool_calls")
    op.drop_index(op.f("ix_chat_messages_session_id"), table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(op.f("ix_chat_sessions_user_id"), table_name="chat_sessions")
    op.drop_index(
        op.f("ix_chat_sessions_collection_id"),
        table_name="chat_sessions",
    )
    op.drop_table("chat_sessions")
