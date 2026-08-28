"""Replace legacy source locators with stable Source artifact references."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0027"
down_revision: str | Sequence[str] | None = "20260812_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("paper_fact_evidence_anchors") as batch_op:
        batch_op.add_column(sa.Column("source_kind", sa.String(length=64)))
        batch_op.add_column(sa.Column("source_ref", sa.String()))

    op.execute(
        """
        UPDATE paper_fact_evidence_anchors
        SET source_kind = CASE
                WHEN block_id IS NOT NULL THEN 'block'
                WHEN figure_or_table IS NOT NULL AND source_type = 'figure' THEN 'figure'
                WHEN figure_or_table IS NOT NULL THEN 'table'
                ELSE 'document'
            END,
            source_ref = COALESCE(
                block_id,
                figure_or_table,
                source_document_id
            )
        """
    )

    with op.batch_alter_table("paper_fact_evidence_anchors") as batch_op:
        batch_op.alter_column("source_kind", nullable=False)
        batch_op.alter_column("source_ref", nullable=False)
        for column_name in (
            "locator_type",
            "locator_confidence",
            "section_id",
            "char_range_json",
            "bbox_json",
            "block_id",
            "snippet_id",
            "figure_or_table",
            "quote_span",
        ):
            batch_op.drop_column(column_name)

    source_columns = {
        "source_blocks": ("bbox_json", "char_range_json"),
        "source_tables": ("bbox_json",),
        "source_table_rows": ("bbox_json",),
        "source_table_cells": ("bbox_json", "char_range_json"),
        "source_figures": ("bbox_json",),
    }
    for table_name, column_names in source_columns.items():
        with op.batch_alter_table(table_name) as batch_op:
            for column_name in column_names:
                batch_op.drop_column(column_name)

    with op.batch_alter_table("source_reference_mentions") as batch_op:
        for constraint_name in (
            "char_start_non_negative",
            "char_end_non_negative",
            "char_range_ordered",
        ):
            batch_op.drop_constraint(constraint_name, type_="check")
        batch_op.drop_column("char_start")
        batch_op.drop_column("char_end")


def downgrade() -> None:
    raise NotImplementedError(
        "revision 20260814_0027 is irreversible because character and PDF "
        "coordinate locators are no longer part of the Source contract"
    )
