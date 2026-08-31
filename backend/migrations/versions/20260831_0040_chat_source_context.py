"""Persist user-selected Source context on Chat messages.

Revision ID: 20260831_0040
Revises: 20260827_0039
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260831_0040"
down_revision: str | Sequence[str] | None = "20260827_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    if "source_contexts" in _chat_message_columns():
        return
    op.add_column(
        "chat_messages",
        sa.Column(
            "source_contexts",
            _JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    if "source_contexts" in _chat_message_columns():
        op.drop_column("chat_messages", "source_contexts")


def _chat_message_columns() -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns("chat_messages")
    }
