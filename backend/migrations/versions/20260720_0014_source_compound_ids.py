"""Allow deterministic compound Source identities.

Revision ID: 20260720_0014
Revises: 20260720_0013
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0014"
down_revision: str | Sequence[str] | None = "20260720_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COMPOUND_ID_COLUMNS = (
    ("source_blocks", "block_id"),
    ("source_block_text_units", "block_id"),
    ("source_tables", "table_id"),
    ("source_tables", "caption_block_id"),
    ("source_table_rows", "row_id"),
    ("source_table_rows", "table_id"),
    ("source_table_cells", "table_id"),
    ("source_figures", "caption_block_id"),
    ("source_reference_entries", "source_block_id"),
    ("source_reference_mentions", "source_block_id"),
    ("paper_fact_evidence_anchors", "block_id"),
    ("paper_fact_evidence_anchors", "figure_or_table"),
    ("objective_frame_table_links", "table_id"),
    ("objective_evidence_routes", "source_ref"),
    ("objective_evidence_routes", "source_block_id"),
    ("objective_evidence_routes", "source_table_id"),
    ("objective_unit_source_refs", "source_ref"),
    ("objective_unit_source_refs", "source_block_id"),
    ("objective_unit_source_refs", "source_table_id"),
)


def upgrade() -> None:
    for table_name, column_name in _COMPOUND_ID_COLUMNS:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                column_name,
                existing_type=sa.String(length=128),
                type_=sa.String(),
            )


def downgrade() -> None:
    for table_name, column_name in reversed(_COMPOUND_ID_COLUMNS):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                column_name,
                existing_type=sa.String(),
                type_=sa.String(length=128),
            )
