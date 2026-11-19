"""Persist administrator assignments of model connections to processing tasks."""

from alembic import op
import sqlalchemy as sa

revision = "20261118_0103"
down_revision = "20261114_0102"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("model_connections", sa.Column(
        "kind", sa.String(16), nullable=False, server_default="chat"
    ))
    op.create_check_constraint("kind", "model_connections", "kind IN ('chat', 'embedding')")
    op.create_table(
        "model_assignments",
        sa.Column("purpose", sa.String(64), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(64),
            sa.ForeignKey("model_connections.connection_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="version_positive"),
    )


def downgrade():
    op.drop_table("model_assignments")
    op.drop_column("model_connections", "kind")
