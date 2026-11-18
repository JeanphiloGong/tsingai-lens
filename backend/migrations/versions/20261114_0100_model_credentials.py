"""Expand provider credentials before the explicit offline key import."""
from alembic import op
import sqlalchemy as sa

revision = "20261114_0100"
down_revision = "20261104_0099"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("model_connections", sa.Column("api_key_ciphertext", sa.LargeBinary(), nullable=True))
    op.add_column("model_connections", sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"))
    checks = {
        "id_length": "length(connection_id) BETWEEN 1 AND 64",
        "name_length": "length(btrim(display_name)) BETWEEN 1 AND 100",
        "base_length": "length(base_url) BETWEEN 1 AND 2048",
        "model_length": "length(btrim(model)) BETWEEN 1 AND 200",
        "version_positive": "version > 0",
        "context_positive": "context_window_tokens IS NULL OR context_window_tokens > 0",
        "output_positive": "max_output_tokens IS NULL OR max_output_tokens > 0",
        "timeout_finite": (
            "request_timeout_seconds IS NULL OR "
            "(request_timeout_seconds > 0 AND request_timeout_seconds < 'Infinity'::float8)"
        ),
        "ciphertext_format": (
            "api_key_ciphertext IS NULL OR (octet_length(api_key_ciphertext) BETWEEN 30 AND 8221 "
            "AND get_byte(api_key_ciphertext, 0) = 1)"
        ),
    }
    for suffix, expression in checks.items():
        op.create_check_constraint(op.f(f"ck_model_connections_{suffix}"), "model_connections", expression)


def downgrade():
    raise RuntimeError("Credential cutover requires restoring the paired database and master-key backup")
