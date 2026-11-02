"""Order available models and the default by operator-configured priority."""
from alembic import op
import sqlalchemy as sa


revision = "20261102_0098"
down_revision = "20261101_0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migration 0038 creates current ORM tables during a full historical replay.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("model_connections")}
    if "priority" in columns:
        return
    op.add_column(
        "model_connections",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("model_connections", "priority")
