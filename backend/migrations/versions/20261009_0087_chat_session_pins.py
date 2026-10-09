"""Persist user-owned chat history pinning."""

from alembic import op
import sqlalchemy as sa


revision = "20261009_0087"
down_revision = "20261008_0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical migration 0038 creates current metadata on fresh databases.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("chat_sessions")}
    if "is_pinned" not in columns:
        op.add_column(
            "chat_sessions",
            sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    op.drop_column("chat_sessions", "is_pinned")
