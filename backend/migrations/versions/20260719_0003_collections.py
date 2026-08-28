"""Add relational collection metadata.

Revision ID: 20260719_0003
Revises: 20260719_0002
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_0003"
down_revision: str | Sequence[str] | None = "20260719_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("paper_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "paper_count >= 0",
            name=op.f("ck_collections_paper_count_non_negative"),
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name=op.f("ck_collections_valid_timestamps"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["auth_users.user_id"],
            name=op.f("fk_collections_owner_user_id_auth_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "collection_id",
            name=op.f("pk_collections"),
        ),
    )
    op.create_index(
        op.f("ix_collections_owner_user_id"),
        "collections",
        ["owner_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_collections_owner_user_id"),
        table_name="collections",
    )
    op.drop_table("collections")
