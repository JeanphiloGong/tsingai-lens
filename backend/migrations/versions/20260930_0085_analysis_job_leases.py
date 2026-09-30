"""Add leases so crashed analysis workers can be recovered."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260930_0085"
down_revision = "20260929_0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("analysis_jobs")}
    additions = (
        ("worker_id", sa.Column("worker_id", sa.String(length=100), nullable=True)),
        ("lease_expires_at", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)),
        ("heartbeat_at", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)),
        ("lease_version", sa.Column("lease_version", sa.Integer(), nullable=False, server_default="0")),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("analysis_jobs", column)

    inspector = inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("analysis_jobs")}
    if "ix_analysis_jobs_worker_id" not in indexes:
        op.create_index("ix_analysis_jobs_worker_id", "analysis_jobs", ["worker_id"])
    if "ix_analysis_jobs_lease_expires_at" not in indexes:
        op.create_index("ix_analysis_jobs_lease_expires_at", "analysis_jobs", ["lease_expires_at"])

    # Rows created before leases cannot be safely resumed at an unknown point.
    # Put them back in the durable queue; the matching Worker will claim them.
    op.execute(
        sa.text(
            "UPDATE analysis_jobs "
            "SET status = 'pending', started_at = NULL, finished_at = NULL, "
            "result_id = NULL, error_code = 'worker_restart_recovery', "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'running'"
        )
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("analysis_jobs")}
    if "ix_analysis_jobs_lease_expires_at" in indexes:
        op.drop_index("ix_analysis_jobs_lease_expires_at", table_name="analysis_jobs")
    if "ix_analysis_jobs_worker_id" in indexes:
        op.drop_index("ix_analysis_jobs_worker_id", table_name="analysis_jobs")
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("analysis_jobs")}
    for name in ("lease_version", "heartbeat_at", "lease_expires_at", "worker_id"):
        if name in columns:
            op.drop_column("analysis_jobs", name)
