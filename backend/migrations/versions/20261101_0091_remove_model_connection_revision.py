"""Give each shared model connection one configuration identified by its ID."""

from alembic import op
import sqlalchemy as sa


revision = "20261101_0091"
down_revision = "20261031_0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Migration 0038 creates current ORM tables during a full historical replay.
    if "revision" not in {
        column["name"] for column in sa.inspect(bind).get_columns("model_connections")
    }:
        return

    if bind.execute(
        sa.text(
            "SELECT connection_id FROM model_connections "
            "GROUP BY connection_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first():
        raise RuntimeError(
            "Assign distinct connection IDs to existing model connection revisions "
            "before upgrading; no configurations were removed"
        )

    op.drop_index("uq_model_connections_enabled_id", table_name="model_connections")
    with op.batch_alter_table("model_connections") as batch:
        batch.drop_constraint(op.f("pk_model_connections"), type_="primary")
        batch.drop_constraint(
            op.f("ck_model_connections_model_connection_revision_positive"), type_="check"
        )
        batch.drop_column("revision")
        batch.create_primary_key(op.f("pk_model_connections"), ["connection_id"])


def downgrade() -> None:
    # Restore the old schema with revision 1; prior revision numbers are not recoverable.
    op.add_column(
        "model_connections",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    with op.batch_alter_table("model_connections") as batch:
        batch.drop_constraint(op.f("pk_model_connections"), type_="primary")
        batch.create_primary_key(
            op.f("pk_model_connections"), ["connection_id", "revision"]
        )
        batch.create_check_constraint(
            op.f("ck_model_connections_model_connection_revision_positive"),
            "revision > 0",
        )
        batch.alter_column("revision", server_default=None)
    op.create_index(
        "uq_model_connections_enabled_id",
        "model_connections",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("enabled"),
    )
