"""Replace build-scoped persistence with the current Document model.

Revision ID: 20260827_0038
Revises: 20260827_0037
Create Date: 2026-08-27 16:00:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import MetaData, inspect

from infra.persistence.postgres.base import Base
import infra.persistence.postgres.models  # noqa: F401


revision = "20260827_0038"
down_revision = "20260827_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    table_names = [
        name
        for name in inspect(bind).get_table_names()
        if name != "alembic_version"
    ]
    if table_names:
        previous = MetaData()
        previous.reflect(bind=bind, only=table_names)
        previous.drop_all(bind=bind)
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    raise RuntimeError(
        "20260827_0038 is an irreversible destructive cutover to current Documents"
    )
