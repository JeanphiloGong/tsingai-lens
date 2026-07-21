"""Allow deterministic compound Source reference identities.

Revision ID: 20260720_0015
Revises: 20260720_0014
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0015"
down_revision: str | Sequence[str] | None = "20260720_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COMPOUND_REFERENCE_ID_COLUMNS = (
    ("source_reference_entries", "reference_id"),
    ("source_reference_mentions", "mention_id"),
    ("source_reference_mentions", "reference_id"),
    ("source_reference_resolutions", "reference_id"),
    ("source_reference_candidates", "candidate_id"),
    ("source_reference_candidates", "reference_id"),
)


def upgrade() -> None:
    for table_name, column_name in _COMPOUND_REFERENCE_ID_COLUMNS:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                column_name,
                existing_type=sa.String(length=128),
                type_=sa.String(),
            )


def downgrade() -> None:
    for table_name, column_name in reversed(_COMPOUND_REFERENCE_ID_COLUMNS):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                column_name,
                existing_type=sa.String(),
                type_=sa.String(length=128),
            )
