"""Persist collection defaults for Research Agent operation permissions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


revision = "20260924_0069"
down_revision = "20260924_0068"
branch_labels = None
depends_on = None


def upgrade():
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("collections")
    }
    if "agent_default_permission" not in existing:
        op.add_column(
            "collections",
            sa.Column("agent_default_permission", _JSON_DOCUMENT, nullable=True),
        )


def downgrade():
    op.drop_column("collections", "agent_default_permission")
