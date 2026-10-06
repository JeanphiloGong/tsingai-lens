"""Persist explicit links between Chat answers and user challenges."""

from alembic import op
import sqlalchemy as sa


revision = "20260923_0061"
down_revision = "20260923_0060"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "chat_correction_cases" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "chat_correction_cases",
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("original_message_id", sa.String(length=128), nullable=False),
        sa.Column("feedback_message_id", sa.String(length=128), nullable=False),
        sa.Column("corrected_message_id", sa.String(length=128), nullable=True),
        sa.Column("original_model_call_id", sa.String(length=64), nullable=False),
        sa.Column("corrected_model_call_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("trace_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["original_message_id"], ["chat_messages.message_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["feedback_message_id"], ["chat_messages.message_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["corrected_message_id"], ["chat_messages.message_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["original_model_call_id"], ["chat_model_calls.call_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["corrected_model_call_id"], ["chat_model_calls.call_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("case_id"),
        sa.CheckConstraint(
            "status IN ('linked', 'unresolved')",
            name="correction_case_status_valid",
        ),
        sa.CheckConstraint(
            "length(trace_digest) = 64",
            name="correction_case_digest_length",
        ),
        sa.CheckConstraint(
            "(status = 'linked' AND corrected_message_id IS NOT NULL AND "
            "corrected_model_call_id IS NOT NULL) OR "
            "(status = 'unresolved' AND corrected_message_id IS NULL AND "
            "corrected_model_call_id IS NULL)",
            name="correction_case_completion_consistent",
        ),
        sa.UniqueConstraint(
            "session_id",
            "original_message_id",
            "feedback_message_id",
            "corrected_message_id",
            name="uq_chat_correction_case_identity",
        ),
    )
    for column in (
        "session_id",
        "original_message_id",
        "feedback_message_id",
        "corrected_message_id",
        "original_model_call_id",
        "corrected_model_call_id",
    ):
        op.create_index(
            f"ix_chat_correction_cases_{column}",
            "chat_correction_cases",
            [column],
        )


def downgrade():
    if "chat_correction_cases" not in sa.inspect(op.get_bind()).get_table_names():
        return
    for column in (
        "corrected_model_call_id",
        "original_model_call_id",
        "corrected_message_id",
        "feedback_message_id",
        "original_message_id",
        "session_id",
    ):
        op.drop_index(
            f"ix_chat_correction_cases_{column}",
            table_name="chat_correction_cases",
        )
    op.drop_table("chat_correction_cases")
