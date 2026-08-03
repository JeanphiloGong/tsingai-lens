"""Rebuild ResearchObjective scientific intent.

Revision ID: 20260802_0020
Revises: 20260722_0019
Create Date: 2026-08-02 16:00:33
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260802_0020"
down_revision: Union[str, Sequence[str], None] = "20260722_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace derived Objective data with the explicit scientific contract."""

    op.execute(
        "UPDATE objective_sessions "
        "SET focused_objective_id = NULL "
        "WHERE focused_objective_id IS NOT NULL"
    )
    op.execute("DELETE FROM research_objectives")
    op.execute("UPDATE objective_builds SET research_objectives_ready = false")

    json_document = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )
    with op.batch_alter_table("research_objectives") as batch_op:
        batch_op.alter_column("process_axes", new_column_name="variables")
        batch_op.alter_column("property_axes", new_column_name="outcomes")
        batch_op.alter_column(
            "comparison_intent",
            new_column_name="requested_comparator",
        )
        batch_op.add_column(
            sa.Column(
                "mechanisms",
                json_document,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "constraints",
                json_document,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )

    with op.batch_alter_table("research_objectives") as batch_op:
        batch_op.alter_column("mechanisms", server_default=None)
        batch_op.alter_column("constraints", server_default=None)


def downgrade() -> None:
    """Old Objective semantics cannot be reconstructed after the rebuild."""

    raise NotImplementedError(
        "20260802_0020 is irreversible: rebuilt Objective intent cannot be "
        "mapped back to process/property axes"
    )
