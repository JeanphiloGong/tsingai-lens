"""Keep the latest response snapshot available across browser connections."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260910_0058"
down_revision = "20260909_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("chat_sessions")}
    if "response_snapshot" not in columns:
        op.add_column("chat_sessions", sa.Column("response_snapshot", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_sessions", "response_snapshot")
