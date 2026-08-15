"""Persist typed pipeline node runtime state.

Revision ID: 20260811_0025
Revises: 20260806_0024
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260811_0025"
down_revision: str | Sequence[str] | None = "20260806_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("collection_builds") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mode",
                sa.String(length=64),
                nullable=False,
                server_default="standard",
            )
        )

    with op.batch_alter_table("build_stages") as batch_op:
        batch_op.drop_constraint(
            op.f("uq_build_stages_build_kind_version"),
            type_="unique",
        )
        batch_op.drop_constraint(
            op.f("ck_build_stages_stage_version_positive"),
            type_="check",
        )
        batch_op.add_column(
            sa.Column(
                "dependencies",
                _JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "stats",
                _JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "output_summary",
                _JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.drop_column("skip_reason")
        batch_op.drop_column("stage_version")
        batch_op.create_unique_constraint(
            op.f("uq_build_stages_build_kind"),
            ["build_id", "stage_kind"],
        )


def downgrade() -> None:
    with op.batch_alter_table("build_stages") as batch_op:
        batch_op.drop_constraint(
            op.f("uq_build_stages_build_kind"),
            type_="unique",
        )
        batch_op.add_column(
            sa.Column(
                "stage_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(sa.Column("skip_reason", sa.Text(), nullable=True))
        batch_op.drop_column("output_summary")
        batch_op.drop_column("stats")
        batch_op.drop_column("dependencies")
        batch_op.create_check_constraint(
            op.f("ck_build_stages_stage_version_positive"),
            "stage_version > 0",
        )
        batch_op.create_unique_constraint(
            op.f("uq_build_stages_build_kind_version"),
            ["build_id", "stage_kind", "stage_version"],
        )

    with op.batch_alter_table("collection_builds") as batch_op:
        batch_op.drop_column("mode")
