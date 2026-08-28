"""remove obsolete Goal-era identity audit table.

The application no longer supports Goal-era SQLite migration or its audit
records. Runtime identity is objective_id only.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260721_0017"
down_revision: Union[str, Sequence[str], None] = "20260720_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("objective_identity_migrations")


def downgrade() -> None:
    # Restore only the empty schema so Alembic's test lifecycle can reverse the
    # revision. Historical Goal identity records are intentionally not restored.
    op.create_table(
        "objective_identity_migrations",
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("backup_reference", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "record_counts",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "content_hashes",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status = 'applied'", name="status_applied"),
        sa.CheckConstraint(
            "length(manifest_sha256) = 64", name="manifest_sha256_length"
        ),
        sa.CheckConstraint(
            "length(source_sha256) = 64", name="source_sha256_length"
        ),
        sa.PrimaryKeyConstraint("source_sha256"),
    )
