"""Add indexes for the chat history navigation query."""

from alembic import op
import sqlalchemy as sa


revision = "20261008_0086"
down_revision = "20260930_0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    session_indexes = {index["name"] for index in inspector.get_indexes("chat_sessions")}
    if "ix_chat_sessions_user_collection_updated" not in session_indexes:
        op.create_index(
            "ix_chat_sessions_user_collection_updated",
            "chat_sessions",
            ["user_id", "collection_id", "updated_at", "session_id"],
            unique=False,
        )

    message_indexes = {index["name"] for index in inspector.get_indexes("chat_messages")}
    if "ix_chat_messages_session_role_position" not in message_indexes:
        op.create_index(
            "ix_chat_messages_session_role_position",
            "chat_messages",
            ["session_id", "role", "position"],
            unique=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    message_indexes = {index["name"] for index in inspector.get_indexes("chat_messages")}
    if "ix_chat_messages_session_role_position" in message_indexes:
        op.drop_index(
            "ix_chat_messages_session_role_position", table_name="chat_messages"
        )

    session_indexes = {index["name"] for index in inspector.get_indexes("chat_sessions")}
    if "ix_chat_sessions_user_collection_updated" in session_indexes:
        op.drop_index(
            "ix_chat_sessions_user_collection_updated", table_name="chat_sessions"
        )
