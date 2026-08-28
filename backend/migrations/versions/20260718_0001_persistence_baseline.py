"""Establish migration-owned schema lineage.

Revision ID: 20260718_0001
Revises:
Create Date: 2026-07-18
"""

from collections.abc import Sequence


revision: str = "20260718_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Establish the empty PostgreSQL baseline."""


def downgrade() -> None:
    """Return to the unversioned baseline."""
