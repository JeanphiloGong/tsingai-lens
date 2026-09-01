"""Remove the retired task output path.

Revision ID: 20260901_0041
Revises: 20260831_0040
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0041"
down_revision: str | Sequence[str] | None = "20260831_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "output_path" in _task_columns():
        op.drop_column("tasks", "output_path")


def downgrade() -> None:
    if "output_path" not in _task_columns():
        op.add_column(
            "tasks",
            sa.Column("output_path", sa.Text(), nullable=True),
        )


def _task_columns() -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns("tasks")
    }
