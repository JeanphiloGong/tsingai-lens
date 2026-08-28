"""Add relational users and browser sessions.

Revision ID: 20260719_0002
Revises: 20260718_0001
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_0002"
down_revision: str | Sequence[str] | None = "20260718_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("auth_users")
