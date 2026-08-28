"""Persist unified objective evidence selection metadata."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0018"
down_revision: Union[str, Sequence[str], None] = "20260721_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("objective_evidence_units") as batch_op:
        batch_op.add_column(sa.Column("source_kind", sa.String(length=32)))
        batch_op.add_column(sa.Column("source_ref", sa.Text()))
        batch_op.add_column(sa.Column("evidence_role", sa.String(length=64)))
        batch_op.add_column(sa.Column("selection_reason", sa.Text()))
        batch_op.add_column(
            sa.Column(
                "selection_status",
                sa.String(length=16),
                nullable=False,
                server_default="extracted",
            )
        )
        batch_op.create_check_constraint(
            "selection_status_valid",
            "selection_status IN ('candidate', 'selected', 'extracted', 'rejected', 'failed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("objective_evidence_units") as batch_op:
        batch_op.drop_constraint("selection_status_valid", type_="check")
        batch_op.drop_column("selection_status")
        batch_op.drop_column("selection_reason")
        batch_op.drop_column("evidence_role")
        batch_op.drop_column("source_ref")
        batch_op.drop_column("source_kind")
