"""Persist owner-scoped Chat correction candidate proposals."""

from alembic import op
import sqlalchemy as sa


revision = "20260923_0064"
down_revision = "20260923_0063"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "chat_correction_candidates" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "chat_correction_candidates",
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("challenge_message_id", sa.String(length=128), nullable=True),
        sa.Column("answer_message_id", sa.String(length=128), nullable=True),
        sa.Column("event_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("model_call_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("proposal", sa.JSON(), nullable=True),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("selected_case_id", sa.String(length=64), nullable=True),
        sa.Column("selected_sample_id", sa.String(length=64), nullable=True),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["auth_users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.collection_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["selected_case_id"], ["chat_correction_cases.case_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["selected_sample_id"], ["chat_correction_samples.sample_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.CheckConstraint(
            "status IN ('needs_review', 'ambiguous', 'no_candidate', 'invalid_proposal', 'provider_failed')",
            name="chat_correction_candidate_status_valid",
        ),
        sa.CheckConstraint("length(digest) = 64", name="chat_correction_candidate_digest_length"),
        sa.CheckConstraint("updated_at >= created_at", name="chat_correction_candidate_times_valid"),
    )
    for column in ("owner_id", "collection_id", "session_id", "status", "digest"):
        op.create_index(
            f"ix_chat_correction_candidates_{column}",
            "chat_correction_candidates",
            [column],
        )


def downgrade():
    bind = op.get_bind()
    if "chat_correction_candidates" not in set(sa.inspect(bind).get_table_names()):
        return
    for column in ("digest", "status", "session_id", "collection_id", "owner_id"):
        op.drop_index(
            f"ix_chat_correction_candidates_{column}",
            table_name="chat_correction_candidates",
        )
    op.drop_table("chat_correction_candidates")
