"""Add Conversation soft-delete state."""

from alembic import op
import sqlalchemy as sa


revision = "b71000000004"
down_revision = "b71000000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_conversations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "chat_conversations_visible_idx",
        "chat_conversations",
        ["user_id", "workspace_id", "updated_at", "conversation_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "chat_conversations_visible_idx",
        table_name="chat_conversations",
    )
    op.drop_column("chat_conversations", "deleted_at")
