"""Cut over legacy Goal conversations to durable Chat.

Revision ID: 20260819_0033
Revises: 20260819_0032
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260819_0033"
down_revision: str | Sequence[str] | None = "20260819_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()),
    "postgresql",
)
_OLD_PLAN_MESSAGE_FK = (
    "fk_objective_experiment_plans_source_message_id_objective_messages"
)
_CHAT_PLAN_MESSAGE_FK = (
    "fk_objective_experiment_plans_source_message_id_chat_messages"
)


def upgrade() -> None:
    connection = op.get_bind()
    legacy_sessions = _legacy_sessions_table()
    legacy_messages = _legacy_messages_table()
    chat_sessions = _chat_sessions_table()
    chat_messages = _chat_messages_table()

    connection.execute(
        sa.insert(chat_sessions).from_select(
            (
                "session_id",
                "user_id",
                "collection_id",
                "created_at",
                "updated_at",
            ),
            sa.select(
                legacy_sessions.c.session_id,
                legacy_sessions.c.user_id,
                legacy_sessions.c.collection_id,
                legacy_sessions.c.created_at,
                legacy_sessions.c.updated_at,
            ).where(
                ~sa.exists(
                    sa.select(1)
                    .select_from(chat_sessions)
                    .where(
                        chat_sessions.c.session_id == legacy_sessions.c.session_id
                    )
                )
            ),
        )
    )
    connection.execute(
        sa.insert(chat_messages).from_select(
            (
                "message_id",
                "session_id",
                "position",
                "role",
                "content",
                "tool_call_id",
                "tool_name",
                "tool_arguments",
                "created_at",
            ),
            sa.select(
                legacy_messages.c.message_id,
                legacy_messages.c.session_id,
                legacy_messages.c.position,
                legacy_messages.c.role,
                legacy_messages.c.content,
                sa.null(),
                sa.null(),
                sa.null(),
                legacy_messages.c.created_at,
            ).where(
                legacy_messages.c.role.in_(("user", "assistant")),
                ~sa.exists(
                    sa.select(1)
                    .select_from(chat_messages)
                    .where(chat_messages.c.message_id == legacy_messages.c.message_id)
                ),
            ),
        )
    )

    with op.batch_alter_table("objective_experiment_plans") as batch_op:
        batch_op.drop_constraint(op.f(_OLD_PLAN_MESSAGE_FK), type_="foreignkey")
        batch_op.create_foreign_key(
            op.f(_CHAT_PLAN_MESSAGE_FK),
            "chat_messages",
            ["source_message_id"],
            ["message_id"],
            ondelete="RESTRICT",
        )

    op.drop_index(op.f("ix_objective_messages_session_id"), table_name="objective_messages")
    op.drop_table("objective_messages")
    op.drop_table("objective_sessions")


def downgrade() -> None:
    _create_legacy_tables()
    connection = op.get_bind()
    legacy_sessions = _legacy_sessions_table()
    legacy_messages = _legacy_messages_table()
    chat_sessions = _chat_sessions_table()
    chat_messages = _chat_messages_table()

    connection.execute(
        sa.insert(legacy_sessions).from_select(
            (
                "session_id",
                "user_id",
                "collection_id",
                "focused_material_id",
                "focused_paper_id",
                "focused_objective_id",
                "goal_text",
                "intent_brief",
                "answer_mode",
                "rolling_summary",
                "last_evidence_ids",
                "last_material_ids",
                "last_paper_ids",
                "collection_data_version",
                "created_at",
                "updated_at",
            ),
            sa.select(
                chat_sessions.c.session_id,
                chat_sessions.c.user_id,
                chat_sessions.c.collection_id,
                sa.null(),
                sa.null(),
                sa.null(),
                sa.null(),
                sa.literal({}, type_=_JSON_DOCUMENT),
                sa.literal("hybrid"),
                sa.literal(""),
                sa.literal([], type_=_JSON_DOCUMENT),
                sa.literal([], type_=_JSON_DOCUMENT),
                sa.literal([], type_=_JSON_DOCUMENT),
                sa.null(),
                chat_sessions.c.created_at,
                chat_sessions.c.updated_at,
            ),
        )
    )
    connection.execute(
        sa.insert(legacy_messages).from_select(
            (
                "message_id",
                "session_id",
                "position",
                "role",
                "content",
                "source_mode",
                "used_evidence_ids",
                "warnings",
                "links",
                "source_links",
                "review_gate",
                "source_finding_refs",
                "created_at",
            ),
            sa.select(
                chat_messages.c.message_id,
                chat_messages.c.session_id,
                chat_messages.c.position,
                chat_messages.c.role,
                chat_messages.c.content,
                sa.null(),
                sa.literal([], type_=_JSON_DOCUMENT),
                sa.literal([], type_=_JSON_DOCUMENT),
                sa.literal({}, type_=_JSON_DOCUMENT),
                sa.literal([], type_=_JSON_DOCUMENT),
                sa.null(),
                sa.literal([], type_=_JSON_DOCUMENT),
                chat_messages.c.created_at,
            ).where(chat_messages.c.role.in_(("user", "assistant"))),
        )
    )

    with op.batch_alter_table("objective_experiment_plans") as batch_op:
        batch_op.drop_constraint(op.f(_CHAT_PLAN_MESSAGE_FK), type_="foreignkey")
        batch_op.create_foreign_key(
            op.f(_OLD_PLAN_MESSAGE_FK),
            "objective_messages",
            ["source_message_id"],
            ["message_id"],
            ondelete="RESTRICT",
        )


def _create_legacy_tables() -> None:
    op.create_table(
        "objective_sessions",
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("focused_material_id", sa.String(length=128), nullable=True),
        sa.Column("focused_paper_id", sa.String(length=128), nullable=True),
        sa.Column("focused_objective_id", sa.String(length=128), nullable=True),
        sa.Column("goal_text", sa.Text(), nullable=True),
        sa.Column("intent_brief", _JSON_DOCUMENT, nullable=False),
        sa.Column("answer_mode", sa.String(length=32), nullable=False),
        sa.Column("rolling_summary", sa.Text(), nullable=False),
        sa.Column("last_evidence_ids", _JSON_DOCUMENT, nullable=False),
        sa.Column("last_material_ids", _JSON_DOCUMENT, nullable=False),
        sa.Column("last_paper_ids", _JSON_DOCUMENT, nullable=False),
        sa.Column("collection_data_version", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth_users.user_id"],
            name=op.f("fk_objective_sessions_user_id_auth_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_objective_sessions_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "focused_objective_id"],
            ["research_objectives.collection_id", "research_objectives.objective_id"],
            name="fk_objective_sessions_focus",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_objective_sessions")),
    )
    op.create_table(
        "objective_messages",
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_mode", sa.String(length=64), nullable=True),
        sa.Column("used_evidence_ids", _JSON_DOCUMENT, nullable=False),
        sa.Column("warnings", _JSON_DOCUMENT, nullable=False),
        sa.Column("links", _JSON_DOCUMENT, nullable=False),
        sa.Column("source_links", _JSON_DOCUMENT, nullable=False),
        sa.Column("review_gate", sa.String(length=64), nullable=True),
        sa.Column("source_finding_refs", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_objective_messages_position_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["objective_sessions.session_id"],
            name=op.f("fk_objective_messages_session_id_objective_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_objective_messages")),
        sa.UniqueConstraint(
            "session_id",
            "position",
            name="uq_objective_messages_position",
        ),
    )
    op.create_index(
        op.f("ix_objective_messages_session_id"),
        "objective_messages",
        ["session_id"],
        unique=False,
    )


def _legacy_sessions_table() -> sa.TableClause:
    return sa.table(
        "objective_sessions",
        sa.column("session_id", sa.String()),
        sa.column("user_id", sa.String()),
        sa.column("collection_id", sa.String()),
        sa.column("focused_material_id", sa.String()),
        sa.column("focused_paper_id", sa.String()),
        sa.column("focused_objective_id", sa.String()),
        sa.column("goal_text", sa.Text()),
        sa.column("intent_brief", _JSON_DOCUMENT),
        sa.column("answer_mode", sa.String()),
        sa.column("rolling_summary", sa.Text()),
        sa.column("last_evidence_ids", _JSON_DOCUMENT),
        sa.column("last_material_ids", _JSON_DOCUMENT),
        sa.column("last_paper_ids", _JSON_DOCUMENT),
        sa.column("collection_data_version", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def _legacy_messages_table() -> sa.TableClause:
    return sa.table(
        "objective_messages",
        sa.column("message_id", sa.String()),
        sa.column("session_id", sa.String()),
        sa.column("position", sa.Integer()),
        sa.column("role", sa.String()),
        sa.column("content", sa.Text()),
        sa.column("source_mode", sa.String()),
        sa.column("used_evidence_ids", _JSON_DOCUMENT),
        sa.column("warnings", _JSON_DOCUMENT),
        sa.column("links", _JSON_DOCUMENT),
        sa.column("source_links", _JSON_DOCUMENT),
        sa.column("review_gate", sa.String()),
        sa.column("source_finding_refs", _JSON_DOCUMENT),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )


def _chat_sessions_table() -> sa.TableClause:
    return sa.table(
        "chat_sessions",
        sa.column("session_id", sa.String()),
        sa.column("user_id", sa.String()),
        sa.column("collection_id", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def _chat_messages_table() -> sa.TableClause:
    return sa.table(
        "chat_messages",
        sa.column("message_id", sa.String()),
        sa.column("session_id", sa.String()),
        sa.column("position", sa.Integer()),
        sa.column("role", sa.String()),
        sa.column("content", sa.Text()),
        sa.column("tool_call_id", sa.String()),
        sa.column("tool_name", sa.String()),
        sa.column("tool_arguments", _JSON_DOCUMENT),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
