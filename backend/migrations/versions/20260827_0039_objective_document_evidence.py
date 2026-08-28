"""Persist independently resumable Objective Evidence per document.

Revision ID: 20260827_0039
Revises: 20260827_0038
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260827_0039"
down_revision: str | Sequence[str] | None = "20260827_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "objective_document_evidence_checkpoints",
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "objective_id"],
            ["research_objectives.collection_id", "research_objectives.objective_id"],
            name="fk_objective_document_evidence_objective",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name="fk_objective_document_evidence_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "collection_id",
            "objective_id",
            "document_id",
            "input_fingerprint",
            name="pk_objective_document_evidence_checkpoints",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_objective_document_evidence_checkpoints_status",
        "objective_document_evidence_checkpoints",
        ["status"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_objective_document_evidence_checkpoints_status",
        table_name="objective_document_evidence_checkpoints",
    )
    op.drop_table("objective_document_evidence_checkpoints")
