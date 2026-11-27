"""Collapse document filename fields into the display filename and storage key."""

from alembic import op
import sqlalchemy as sa

revision = "20261127_0104"
down_revision = "20261118_0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "documents",
        "original_filename",
        new_column_name="filename",
        existing_type=sa.Text(),
        existing_nullable=False,
    )
    op.drop_column("documents", "stored_filename")


def downgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("stored_filename", sa.Text(), nullable=True),
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE documents
            SET stored_filename = filename
            WHERE stored_filename IS NULL
            """
        )
    )
    op.alter_column(
        "documents",
        "stored_filename",
        nullable=False,
        existing_type=sa.Text(),
    )
    op.alter_column(
        "documents",
        "filename",
        new_column_name="original_filename",
        existing_type=sa.Text(),
        existing_nullable=False,
    )
