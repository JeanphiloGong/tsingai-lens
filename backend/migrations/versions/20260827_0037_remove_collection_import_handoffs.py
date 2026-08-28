"""Remove obsolete collection import manifests and goal handoffs.

Revision ID: 20260827_0037
Revises: 20260825_0036
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260827_0037"
down_revision: str | Sequence[str] | None = "20260825_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("collection_import_documents")
    op.drop_table("collection_imports")
    op.drop_table("collection_handoffs")


def downgrade() -> None:
    raise NotImplementedError(
        "revision 20260827_0037 is irreversible because retired collection "
        "import and handoff records are not part of the current domain model"
    )
