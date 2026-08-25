"""Persist adaptive Paper Map and review-author knowledge semantics.

Revision ID: 20260825_0036
Revises: 20260821_0035
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260825_0036"
down_revision: str | Sequence[str] | None = "20260821_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("objective_paper_skims") as batch_op:
        batch_op.add_column(
            sa.Column(
                "map_status",
                sa.String(length=32),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.add_column(
            sa.Column(
                "map_limitations",
                _JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "review_synthesis",
                _JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.create_check_constraint(
            "paper_map_status_valid",
            "map_status IN ('unknown', 'sufficient', 'insufficient_map')",
        )


def downgrade() -> None:
    with op.batch_alter_table("objective_paper_skims") as batch_op:
        batch_op.drop_constraint("paper_map_status_valid", type_="check")
        batch_op.drop_column("review_synthesis")
        batch_op.drop_column("map_limitations")
        batch_op.drop_column("map_status")
