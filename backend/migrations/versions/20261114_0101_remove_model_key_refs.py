"""Finish the explicit key import; runtime has no environment-reference fallback."""
from alembic import op
import sqlalchemy as sa

revision = "20261114_0101"
down_revision = "20261114_0100"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    remaining = bind.execute(sa.text("""
        SELECT count(*) FROM model_connections
        WHERE api_key_ref IS NOT NULL AND api_key_ciphertext IS NULL
    """)).scalar_one()
    if remaining:
        raise RuntimeError("Import all provider key references before removing the legacy column")
    op.drop_column("model_connections", "api_key_ref")


def downgrade():
    raise RuntimeError(
        "Credential cutover is irreversible. Restore the pre-cutover backup. "
        "Encrypted keys cannot reconstruct environment references."
    )
