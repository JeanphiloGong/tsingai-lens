"""Replace build-scoped persistence with the current Document model.

Revision ID: 20260827_0038
Revises: 20260827_0037
Create Date: 2026-08-27 16:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Column, DateTime, Float, ForeignKey, JSON, MetaData, String, Table, Text, inspect

from infra.persistence.postgres.base import Base
import infra.persistence.postgres.models  # noqa: F401


revision = "20260827_0038"
down_revision = "20260827_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    table_names = [
        name for name in inspect(bind).get_table_names() if name != "alembic_version"
    ]
    if table_names:
        previous = MetaData()
        previous.reflect(bind=bind, only=table_names)
        previous.drop_all(bind=bind)
    # Preserve the historical identity schema for revisions 0042–0087.
    # Runtime identity ownership moves only at 0088.
    op.create_table(
        "auth_users",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "email = lower(email)",
            name=op.f("ck_auth_users_email_normalized"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_auth_users")),
        sa.UniqueConstraint("email", name=op.f("uq_auth_users_email")),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_auth_sessions_valid_expiry"),
        ),
        sa.CheckConstraint(
            "token_hash = lower(token_hash)",
            name=op.f("ck_auth_sessions_token_hash_lowercase"),
        ),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name=op.f("ck_auth_sessions_token_hash_length"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth_users.user_id"],
            name=op.f("fk_auth_sessions_user_id_auth_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint(
            "token_hash",
            name=op.f("uq_auth_sessions_token_hash"),
        ),
    )
    op.create_index(
        op.f("ix_auth_sessions_user_id"),
        "auth_sessions",
        ["user_id"],
        unique=False,
    )
    # This revision historically created the pre-0054 profile table through
    # the then-current ORM. Keep that legacy shape explicit so later
    # migrations can backfill it even though the maintained ORM now owns the
    # merged document_preparations table.
    # Answer feedback is introduced by 0056, not this historical cutover.
    # Model connections are introduced by 0089 with the original schema.
    # Model connection audit is introduced by 0102.
    Base.metadata.create_all(
        bind=bind,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if table.name not in {
                "chat_message_feedback",
                "model_connections",
                "model_connection_audit",
            }
        ],
    )
    if "document_preparations" in inspect(bind).get_table_names():
        op.drop_table("document_preparations")
    legacy = MetaData()
    legacy.reflect(bind=bind, only=("documents", "collections"))
    profiles = Table(
        "document_profiles",
        legacy,
        Column(
            "document_id",
            String(128),
            ForeignKey("documents.document_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        Column("title", Text, nullable=True),
        Column("doc_type", String(32), nullable=False),
        Column("profile_warnings", JSON, nullable=False),
        Column("confidence", Float, nullable=False),
    )
    sources = Table(
        "document_sources",
        legacy,
        Column(
            "document_id",
            String(64),
            ForeignKey("documents.document_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        Column("source_format", String(32), nullable=False),
        Column("parser_name", String(128), nullable=False),
        Column("parser_version", String(128), nullable=False),
        Column("source_fingerprint", String(64), nullable=False),
        Column("artifact_json", JSON, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    legacy.create_all(bind=bind, tables=[profiles, sources])


def downgrade() -> None:
    raise RuntimeError(
        "20260827_0038 is an irreversible destructive cutover to current Documents"
    )
