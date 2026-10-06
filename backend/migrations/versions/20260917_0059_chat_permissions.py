"""Store session-scoped permission and exact call authorization provenance."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260917_0059"
down_revision = "20260910_0058"
branch_labels = None
depends_on = None


def upgrade():
    for table, columns in (
        ("chat_sessions", [sa.Column("operation_permission", postgresql.JSONB(), nullable=True)]),
        ("chat_tool_calls", [
            sa.Column("decision_basis", sa.String(32), nullable=False, server_default="explicit"),
            sa.Column("authorization_revision", sa.Integer(), nullable=True),
            sa.Column("proposed_permission_revision", sa.Integer(), nullable=False, server_default="0"),
        ]),
    ):
        existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade():
    op.drop_column("chat_tool_calls", "proposed_permission_revision")
    op.drop_column("chat_tool_calls", "authorization_revision")
    op.drop_column("chat_tool_calls", "decision_basis")
    op.drop_column("chat_sessions", "operation_permission")
