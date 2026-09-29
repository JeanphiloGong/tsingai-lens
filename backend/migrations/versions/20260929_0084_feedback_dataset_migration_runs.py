"""Record legacy feedback dataset migration plans and outcomes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260929_0084"
down_revision = "20260929_0083"
branch_labels = None
depends_on = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    if "feedback_dataset_migration_runs" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "feedback_dataset_migration_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("migration_version", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary", _JSON_DOCUMENT, nullable=False),
        sa.Column("items", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name="pk_feedback_dataset_migration_runs"),
        sa.CheckConstraint(
            "mode IN ('dry_run', 'apply')",
            name="feedback_dataset_migration_run_mode_valid",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'applied', 'failed')",
            name="feedback_dataset_migration_run_status_valid",
        ),
    )
    op.create_index(
        "ix_feedback_dataset_migration_runs_created",
        "feedback_dataset_migration_runs",
        ["created_at"],
    )


def downgrade() -> None:
    if "feedback_dataset_migration_runs" not in inspect(op.get_bind()).get_table_names():
        return
    op.drop_index(
        "ix_feedback_dataset_migration_runs_created",
        table_name="feedback_dataset_migration_runs",
    )
    op.drop_table("feedback_dataset_migration_runs")
