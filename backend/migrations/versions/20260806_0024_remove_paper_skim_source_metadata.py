"""Remove duplicated Source metadata from Objective paper skims."""

from __future__ import annotations

from alembic import op


revision = "20260806_0024"
down_revision = "20260802_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("objective_paper_skims") as batch_op:
        batch_op.drop_column("title")
        batch_op.drop_column("source_filename")


def downgrade() -> None:
    raise NotImplementedError(
        "revision 20260806_0024 is irreversible because PaperSkim metadata "
        "remains owned by Source documents"
    )
