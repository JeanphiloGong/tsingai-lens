"""Preserve conversation alternatives without rewriting their original trajectory."""

from alembic import op
import sqlalchemy as sa

revision = "20260909_0057"
down_revision = "20260909_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The bootstrap migration creates tables from current ORM metadata on empty databases.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("chat_sessions")}
    for name, column_type in (
        ("root_session_id", sa.String(128)), ("parent_session_id", sa.String(128)),
        ("fork_message_id", sa.String(128)), ("fork_position", sa.Integer()),
        ("fork_content", sa.Text()),
    ):
        if name not in columns:
            op.add_column("chat_sessions", sa.Column(name, column_type, nullable=True))
    if "ix_chat_sessions_root_session_id" not in {index["name"] for index in inspector.get_indexes("chat_sessions")}:
        op.create_index("ix_chat_sessions_root_session_id", "chat_sessions", ["root_session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_root_session_id", table_name="chat_sessions")
    for name in ("fork_content", "fork_position", "fork_message_id", "parent_session_id", "root_session_id"):
        op.drop_column("chat_sessions", name)
