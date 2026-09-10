"""Persist a user's usefulness feedback separately from Chat trajectories."""

from alembic import op
import sqlalchemy as sa


revision = "20260909_0056"
down_revision = "20260908_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_message_feedback",
        sa.Column("feedback_id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(128), sa.ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(128), sa.ForeignKey("chat_messages.message_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("auth_users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(16), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("response_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "message_id", name="uq_chat_message_feedback_user_message"),
        sa.CheckConstraint("rating IN ('helpful', 'not_helpful')", name="rating_valid"),
        sa.CheckConstraint(
            "reason IS NULL OR (rating = 'not_helpful' AND "
            "reason IN ('incorrect', 'incomplete', 'unclear', 'other'))",
            name="reason_valid",
        ),
        sa.CheckConstraint("comment IS NULL OR length(comment) <= 2000", name="comment_length"),
        sa.CheckConstraint("length(response_digest) = 64", name="digest_length"),
        sa.CheckConstraint("updated_at >= created_at", name="valid_timestamps"),
    )
    op.create_index("ix_chat_message_feedback_session_id", "chat_message_feedback", ["session_id"])
    op.create_index("ix_chat_message_feedback_message_id", "chat_message_feedback", ["message_id"])


def downgrade() -> None:
    op.drop_table("chat_message_feedback")
