"""Remove local identity storage; existing databases require verified import first."""

from alembic import op
from sqlalchemy import inspect

revision = "20261104_0099"
down_revision = "20261102_0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    for table in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(table):
            if foreign_key["referred_table"] == "auth_users":
                op.drop_constraint(foreign_key["name"], table, type_="foreignkey")
    tables = inspector.get_table_names()
    for table in ("auth_sessions", "auth_users"):
        if table in tables:
            op.drop_table(table)


def downgrade() -> None:
    raise RuntimeError(
        "Identity cutover is irreversible; restore the pre-cutover database backup."
    )
