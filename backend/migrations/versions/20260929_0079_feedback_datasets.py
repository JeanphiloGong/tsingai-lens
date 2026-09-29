"""Create maintained feedback dataset definitions.

This table is intentionally separate from ``feedback_dataset_snapshots``.
Snapshots are immutable historical exports; datasets own a task type and live
long enough to receive samples and revisions.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260929_0079"
down_revision = "20260927_0078"
branch_labels = None
depends_on = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "feedback_datasets" in inspector.get_table_names():
        return
    op.create_table(
        "feedback_datasets",
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("task_type", sa.String(length=16), nullable=False),
        sa.Column("construction_spec", _JSON_DOCUMENT, nullable=False),
        sa.Column("spec_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name="fk_feedback_datasets_collection",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.user_id"],
            name="fk_feedback_datasets_created_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_feedback_datasets"),
        sa.CheckConstraint(
            "task_type IN ('sft', 'preference', 'evaluation')",
            name="feedback_dataset_task_type_valid",
        ),
        sa.CheckConstraint(
            "spec_version >= 1",
            name="feedback_dataset_spec_version_positive",
        ),
    )
    op.create_index(
        "ix_feedback_datasets_collection_created",
        "feedback_datasets",
        ["collection_id", "created_at"],
    )
    op.create_index(
        "ix_feedback_datasets_created_by",
        "feedback_datasets",
        ["created_by"],
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "feedback_datasets" not in inspector.get_table_names():
        return
    op.drop_index("ix_feedback_datasets_created_by", table_name="feedback_datasets")
    op.drop_index(
        "ix_feedback_datasets_collection_created",
        table_name="feedback_datasets",
    )
    op.drop_table("feedback_datasets")
