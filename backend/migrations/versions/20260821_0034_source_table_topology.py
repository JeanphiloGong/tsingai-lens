"""Preserve logical table topology from Source parsers."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_0034"
down_revision: str | Sequence[str] | None = "20260819_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source_tables") as batch_op:
        batch_op.add_column(
            sa.Column(
                "header_row_count",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.create_check_constraint(
            "header_row_count_non_negative",
            "header_row_count >= 0",
        )

    with op.batch_alter_table("source_table_cells") as batch_op:
        batch_op.add_column(
            sa.Column("row_span", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("col_span", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column(
                "column_header",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "row_header",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "row_section",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_check_constraint("row_span_positive", "row_span >= 1")
        batch_op.create_check_constraint("col_span_positive", "col_span >= 1")

    with op.batch_alter_table("source_tables") as batch_op:
        batch_op.alter_column("header_row_count", server_default=None)
    with op.batch_alter_table("source_table_cells") as batch_op:
        for column_name in (
            "row_span",
            "col_span",
            "column_header",
            "row_header",
            "row_section",
        ):
            batch_op.alter_column(column_name, server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("source_table_cells") as batch_op:
        batch_op.drop_constraint("col_span_positive", type_="check")
        batch_op.drop_constraint("row_span_positive", type_="check")
        batch_op.drop_column("row_section")
        batch_op.drop_column("row_header")
        batch_op.drop_column("column_header")
        batch_op.drop_column("col_span")
        batch_op.drop_column("row_span")

    with op.batch_alter_table("source_tables") as batch_op:
        batch_op.drop_constraint("header_row_count_non_negative", type_="check")
        batch_op.drop_column("header_row_count")
