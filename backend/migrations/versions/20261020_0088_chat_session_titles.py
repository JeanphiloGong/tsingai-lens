"""Persist user-defined chat session titles."""

from alembic import op
import sqlalchemy as sa

revision = "20261020_0088"
down_revision = "20261009_0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("chat_sessions")}
    if "title" not in columns:
        op.add_column("chat_sessions", sa.Column("title", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_sessions", "title")
