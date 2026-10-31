"""Persist ownership for document preparation, discovery, and analysis workers.

Stop the old application workers before upgrading; legacy running executions
become eligible for takeover. Published scientific results are unchanged.
"""

from datetime import datetime, timedelta, timezone
from alembic import op
import sqlalchemy as sa

revision = "20261031_0090"
down_revision = "20261025_0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in ("pipeline_runs", "objective_analyses"):
        # Migration 0038 creates current ORM tables during a full historical replay.
        # Existing installations still require the explicit additions below.
        existing = {item["name"] for item in sa.inspect(bind).get_columns(table)}
        columns = (
            sa.Column("worker_id", sa.String(255), nullable=True),
            sa.Column(
                "lease_version", sa.Integer(), server_default="0", nullable=False
            ),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        )
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
        bind.execute(
            sa.text(
                f"UPDATE {table} SET lease_expires_at = :expired WHERE status = 'running' AND worker_id IS NULL"
            ).bindparams(sa.bindparam("expired", type_=sa.DateTime(timezone=True))),
            {"expired": datetime.now(timezone.utc) - timedelta(seconds=1)},
        )
        index_name = f"ix_{table}_worker_claim"
        if index_name not in {
            item["name"] for item in sa.inspect(bind).get_indexes(table)
        }:
            columns = (["pipeline_name"] if table == "pipeline_runs" else []) + [
                "status",
                "lease_expires_at",
                "created_at",
            ]
            op.create_index(index_name, table, columns)


def downgrade() -> None:
    for table in ("pipeline_runs", "objective_analyses"):
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT 1 FROM {table} WHERE status = 'running' LIMIT 1"))
            .first()
        ):
            raise RuntimeError(
                "Stop and finish running research jobs before removing their leases"
            )
    op.drop_index("ix_objective_analyses_worker_claim", table_name="objective_analyses")
    op.drop_index("ix_pipeline_runs_worker_claim", table_name="pipeline_runs")
    for table in ("objective_analyses", "pipeline_runs"):
        for column in (
            "heartbeat_at",
            "lease_expires_at",
            "lease_version",
            "worker_id",
        ):
            op.drop_column(table, column)
