"""Add mutable Research Objective lifecycle.

Revision ID: 20260720_0012
Revises: 20260720_0011
Create Date: 2026-07-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260720_0012"
down_revision: Union[str, Sequence[str], None] = "20260720_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_objective_lifecycles",
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("source_build_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("analysis_error", sa.Text(), nullable=True),
        sa.Column(
            "analysis_progress",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()),
                "postgresql",
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('confirmed', 'queued', 'running', 'ready', 'failed')",
            name=op.f("ck_research_objective_lifecycles_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "source_build_id", "objective_id"],
            [
                "research_objectives.collection_id",
                "research_objectives.build_id",
                "research_objectives.objective_id",
            ],
            name="fk_objective_lifecycles_objective",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "collection_id",
            "objective_id",
            name=op.f("pk_research_objective_lifecycles"),
        ),
    )
def downgrade() -> None:
    op.drop_table("research_objective_lifecycles")
