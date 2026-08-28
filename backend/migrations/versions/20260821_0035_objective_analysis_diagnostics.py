"""Persist private Objective analysis diagnostics.

Revision ID: 20260821_0035
Revises: 20260821_0034
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260821_0035"
down_revision: str | Sequence[str] | None = "20260821_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("objective_analyses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "diagnostics",
                _JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("objective_analyses") as batch_op:
        batch_op.drop_column("diagnostics")
