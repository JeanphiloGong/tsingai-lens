"""Persist immutable Chat correction samples and append-only reviews."""

from alembic import op
import sqlalchemy as sa


revision = "20260923_0062"
down_revision = "20260923_0061"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "chat_correction_samples" not in tables:
        op.create_table(
            "chat_correction_samples",
            sa.Column("sample_id", sa.String(length=64), nullable=False),
            sa.Column("case_id", sa.String(length=64), nullable=False),
            sa.Column("session_id", sa.String(length=128), nullable=False),
            sa.Column("collection_id", sa.String(length=64), nullable=False),
            sa.Column("model_call_id", sa.String(length=64), nullable=False),
            sa.Column("input", sa.JSON(), nullable=False),
            sa.Column("observations", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("target", sa.Text(), nullable=False),
            sa.Column("source_refs", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("digest", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["case_id"], ["chat_correction_cases.case_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.session_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["collection_id"], ["collections.collection_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["model_call_id"], ["chat_model_calls.call_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("sample_id"),
            sa.CheckConstraint("length(digest) = 64", name="chat_correction_sample_digest_length"),
            sa.CheckConstraint("length(target) > 0", name="chat_correction_sample_target_nonempty"),
            sa.UniqueConstraint("case_id", name="uq_chat_correction_sample_case"),
        )
        for column in ("case_id", "session_id", "collection_id", "model_call_id", "digest"):
            op.create_index(
                f"ix_chat_correction_samples_{column}",
                "chat_correction_samples",
                [column],
            )
    if "chat_correction_reviews" not in tables:
        op.create_table(
            "chat_correction_reviews",
            sa.Column("review_id", sa.String(length=64), nullable=False),
            sa.Column("sample_id", sa.String(length=64), nullable=False),
            sa.Column("session_id", sa.String(length=128), nullable=False),
            sa.Column("sample_digest", sa.String(length=64), nullable=False),
            sa.Column("decision", sa.String(length=16), nullable=False),
            sa.Column("reviewer_id", sa.String(length=64), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("support_message_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["sample_id"], ["chat_correction_samples.sample_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.session_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["reviewer_id"], ["auth_users.user_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("review_id"),
            sa.CheckConstraint(
                "decision IN ('accept', 'reject', 'insufficient', 'withdraw')",
                name="chat_correction_review_decision_valid",
            ),
            sa.CheckConstraint("seq >= 1", name="chat_correction_review_seq_positive"),
            sa.CheckConstraint("length(sample_digest) = 64", name="chat_correction_review_digest_length"),
            sa.UniqueConstraint("sample_id", "seq", name="uq_chat_correction_review_sample_seq"),
        )
        for column in ("sample_id", "session_id", "reviewer_id"):
            op.create_index(
                f"ix_chat_correction_reviews_{column}",
                "chat_correction_reviews",
                [column],
            )


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "chat_correction_reviews" in tables:
        for column in ("reviewer_id", "session_id", "sample_id"):
            op.drop_index(
                f"ix_chat_correction_reviews_{column}",
                table_name="chat_correction_reviews",
            )
        op.drop_table("chat_correction_reviews")
    if "chat_correction_samples" in tables:
        for column in ("digest", "model_call_id", "collection_id", "session_id", "case_id"):
            op.drop_index(
                f"ix_chat_correction_samples_{column}",
                table_name="chat_correction_samples",
            )
        op.drop_table("chat_correction_samples")
