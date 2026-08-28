"""Persist user-approved Objective candidate provenance.

Revision ID: 20260819_0032
Revises: 20260819_0031
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260819_0032"
down_revision: str | Sequence[str] | None = "20260819_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()),
    "postgresql",
)


def upgrade() -> None:
    op.create_table(
        "objective_authored_candidates",
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("source_build_id", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("seed_document_ids", _JSON_DOCUMENT, nullable=False),
        sa.Column("excluded_document_ids", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_by_user_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "origin = 'chat_assisted'",
            name=op.f("ck_objective_authored_candidates_origin_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "objective_id"],
            ["research_objectives.collection_id", "research_objectives.objective_id"],
            name="fk_objective_authored_candidates_objective",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "source_build_id"],
            ["objective_builds.collection_id", "objective_builds.build_id"],
            name="fk_objective_authored_candidates_source_build",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["auth_users.user_id"],
            name=op.f(
                "fk_objective_authored_candidates_created_by_user_id_auth_users"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "collection_id",
            "objective_id",
            name=op.f("pk_objective_authored_candidates"),
        ),
        sa.UniqueConstraint(
            "created_by_tool_call_id",
            name="uq_objective_authored_candidates_tool_call",
        ),
    )


def downgrade() -> None:
    op.drop_table("objective_authored_candidates")
