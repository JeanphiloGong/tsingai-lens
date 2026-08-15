"""Persist per-paper Objective evidence disposition.

Revision ID: 20260814_0030
Revises: 20260814_0029
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0030"
down_revision: str | Sequence[str] | None = "20260814_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("objective_paper_contributions") as batch_op:
        batch_op.add_column(
            sa.Column("evidence_disposition", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(
            sa.Column("routed_source_count", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("extracted_source_count", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("comparable_evidence_count", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("failed_source_count", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("evidence_disposition_reason", sa.Text(), nullable=True)
        )
        batch_op.create_check_constraint(
            op.f("ck_objective_paper_contributions_evidence_disposition_valid"),
            "evidence_disposition IS NULL OR evidence_disposition IN "
            "('excluded', 'no_routable_evidence', 'extraction_failed', "
            "'no_comparable_evidence', 'comparable_evidence')",
        )
        batch_op.create_check_constraint(
            op.f("ck_objective_paper_contributions_evidence_counts_non_negative"),
            "(routed_source_count IS NULL OR routed_source_count >= 0) AND "
            "(extracted_source_count IS NULL OR extracted_source_count >= 0) AND "
            "(comparable_evidence_count IS NULL OR comparable_evidence_count >= 0) AND "
            "(failed_source_count IS NULL OR failed_source_count >= 0)",
        )
        batch_op.create_check_constraint(
            op.f("ck_objective_paper_contributions_evidence_accounting_complete"),
            "(evidence_disposition IS NULL AND routed_source_count IS NULL AND "
            "extracted_source_count IS NULL AND comparable_evidence_count IS NULL AND "
            "failed_source_count IS NULL) OR "
            "(evidence_disposition IS NOT NULL AND routed_source_count IS NOT NULL AND "
            "extracted_source_count IS NOT NULL AND comparable_evidence_count IS NOT NULL AND "
            "failed_source_count IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("objective_paper_contributions") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_objective_paper_contributions_evidence_accounting_complete"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_objective_paper_contributions_evidence_counts_non_negative"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_objective_paper_contributions_evidence_disposition_valid"),
            type_="check",
        )
        batch_op.drop_column("evidence_disposition_reason")
        batch_op.drop_column("failed_source_count")
        batch_op.drop_column("comparable_evidence_count")
        batch_op.drop_column("extracted_source_count")
        batch_op.drop_column("routed_source_count")
        batch_op.drop_column("evidence_disposition")
