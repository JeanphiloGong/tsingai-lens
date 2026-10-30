"""Add one table for versioned shared model connections."""
from alembic import op
import sqlalchemy as sa


revision = "20261025_0089"
down_revision = "20261020_0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "model_connections" in inspector.get_table_names():
        return
    op.create_table(
        "model_connections",
        sa.Column("connection_id", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("api_key_ref", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("context_window_tokens", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("request_timeout_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("connection_id", "revision"),
        sa.CheckConstraint(
            "revision > 0",
            name=op.f("ck_model_connections_model_connection_revision_positive"),
        ),
    )
    op.create_index("ix_model_connections_enabled", "model_connections", ["enabled"])
    op.create_index(
        "uq_model_connections_enabled_id",
        "model_connections",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("enabled"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "model_connections" not in sa.inspect(bind).get_table_names():
        return
    if bind.execute(sa.text("SELECT COUNT(*) FROM model_connections")).scalar_one():
        raise RuntimeError("model connection history must be exported before downgrade")
    op.drop_index("uq_model_connections_enabled_id", table_name="model_connections")
    op.drop_index("ix_model_connections_enabled", table_name="model_connections")
    op.drop_table("model_connections")
