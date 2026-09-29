"""Record idempotent dataset sample actions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260929_0082"
down_revision = "20260929_0081"
branch_labels = None
depends_on = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    if "feedback_sample_actions" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "feedback_sample_actions",
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("sample_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("expected_revision_id", sa.String(length=64), nullable=True),
        sa.Column("previous_status", sa.String(length=32), nullable=False),
        sa.Column("next_status", sa.String(length=32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("result_sample", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["sample_id"], ["feedback_dataset_samples.sample_id"],
            name="fk_feedback_sample_actions_sample", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["auth_users.user_id"],
            name="fk_feedback_sample_actions_actor", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["analysis_jobs.job_id"],
            name="fk_feedback_sample_actions_job", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("action_id", name="pk_feedback_sample_actions"),
        sa.UniqueConstraint(
            "sample_id", "idempotency_key", name="uq_feedback_sample_actions_key"
        ),
        sa.CheckConstraint(
            "generation >= 1", name="feedback_sample_action_generation_positive"
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64", name="feedback_sample_action_digest_length"
        ),
        sa.CheckConstraint(
            "action IN ('rebuild', 'retry', 'discard', 'restore')",
            name="feedback_sample_action_type_valid",
        ),
    )
    op.create_index(
        "ix_feedback_sample_actions_sample_created",
        "feedback_sample_actions",
        ["sample_id", "created_at"],
    )


def downgrade() -> None:
    if "feedback_sample_actions" not in inspect(op.get_bind()).get_table_names():
        return
    op.drop_index(
        "ix_feedback_sample_actions_sample_created", table_name="feedback_sample_actions"
    )
    op.drop_table("feedback_sample_actions")
