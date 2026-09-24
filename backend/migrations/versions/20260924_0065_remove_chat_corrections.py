"""Remove retired Chat correction and model-request recording tables."""

from alembic import op
from alembic.script import ScriptDirectory
import sqlalchemy as sa


revision = "20260924_0065"
down_revision = "20260923_0064"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    # Drop dependents first; ordinary conversations and feedback are retained.
    for table in (
        "chat_correction_candidates",
        "chat_correction_datasets",
        "chat_correction_reviews",
        "chat_correction_samples",
        "chat_correction_cases",
        "chat_model_calls",
    ):
        if table in tables:
            op.drop_table(table)


def downgrade():
    # Recreate the historical schema, without claiming to restore deleted data.
    scripts = ScriptDirectory.from_config(op.get_context().config)
    for previous in (
        "20260923_0060",
        "20260923_0061",
        "20260923_0062",
        "20260923_0063",
        "20260923_0064",
    ):
        scripts.get_revision(previous).module.upgrade()
