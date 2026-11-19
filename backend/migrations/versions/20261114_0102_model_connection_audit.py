"""Record atomic, redacted model administration changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261114_0102"
down_revision = "20261114_0101"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_connection_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("connection_id", sa.String(64), sa.ForeignKey("model_connections.connection_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("actor_display_name", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("changes", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(actor_id) BETWEEN 1 AND 64", name="actor_length"),
        sa.CheckConstraint("action IN ('create', 'update')", name="action"),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.CheckConstraint("jsonb_typeof(changes) = 'object'", name="changes_object"),
        sa.UniqueConstraint("connection_id", "version"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM model_connection_audit")).scalar_one():
        raise RuntimeError("Export and retain administrative audit records before downgrade")
    op.drop_table("model_connection_audit")
