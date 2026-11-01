"""Record the selected model connection on provider calls."""
from alembic import op
import sqlalchemy as sa


revision = "20261101_0092"
down_revision = "20261101_0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("chat_model_calls")
    }
    if "model_connection_id" not in columns:
        op.add_column(
            "chat_model_calls",
            sa.Column("model_connection_id", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("chat_model_calls")
    }
    if "model_connection_id" in columns:
        op.drop_column("chat_model_calls", "model_connection_id")
