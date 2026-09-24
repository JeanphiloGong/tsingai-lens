"""Persist Findings as references to selections and optional groups."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260924_0070"
down_revision = "20260924_0069"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "finding",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("finding_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("factors_json", postgresql.JSONB(), nullable=False),
        sa.Column("outcome", sa.String(length=300), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("assertion_strength", sa.String(length=20), nullable=False),
        sa.Column("attribution_scope", sa.String(length=30), nullable=False),
        sa.Column("synthesis_status", sa.String(length=40), nullable=False),
        sa.Column("certainty", sa.Float(), nullable=False),
        sa.Column("display_rank", sa.Integer(), nullable=False),
        sa.Column("mechanisms_json", postgresql.JSONB(), nullable=False),
        sa.Column("scientific_context_json", postgresql.JSONB(), nullable=False),
        sa.Column("limitations_json", postgresql.JSONB(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("source_analysis_version", sa.Integer(), nullable=True),
        sa.Column("parent_finding_id", sa.String(length=128), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=128), nullable=True),
        sa.Column("created_by_tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warnings_json", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_finding_objective_analysis",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_finding"),
        sa.UniqueConstraint("finding_id", name="uq_finding_identity"),
        sa.CheckConstraint("analysis_version > 0", name="finding_analysis_version_positive"),
        sa.CheckConstraint("certainty >= 0 AND certainty <= 1", name="finding_certainty_range"),
        sa.CheckConstraint("display_rank >= 0", name="finding_display_rank_non_negative"),
    )
    op.create_index("ix_finding_collection_id", "finding", ["collection_id"])
    op.create_index(
        "ix_finding_objective_analysis",
        "finding",
        ["objective_id", "analysis_version"],
    )

    op.create_table(
        "finding_selection",
        sa.Column("finding_id", sa.String(length=128), nullable=False),
        sa.Column("selection_id", sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["finding.finding_id"],
            name="fk_finding_selection_finding",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["selection_id"],
            ["objective_experiment_selection.selection_id"],
            name="fk_finding_selection_selection",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "finding_id",
            "selection_id",
            name="pk_finding_selection",
        ),
    )
    op.create_index(
        "ix_finding_selection_selection_id",
        "finding_selection",
        ["selection_id"],
    )

    op.create_table(
        "finding_comparison_group",
        sa.Column("finding_id", sa.String(length=128), nullable=False),
        sa.Column("group_id", sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["finding.finding_id"],
            name="fk_finding_comparison_group_finding",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["comparison_group.group_id"],
            name="fk_finding_comparison_group_group",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "finding_id",
            "group_id",
            name="pk_finding_comparison_group",
        ),
    )
    op.create_index(
        "ix_finding_comparison_group_group_id",
        "finding_comparison_group",
        ["group_id"],
    )


def downgrade():
    op.drop_index(
        "ix_finding_comparison_group_group_id",
        table_name="finding_comparison_group",
    )
    op.drop_table("finding_comparison_group")
    op.drop_index("ix_finding_selection_selection_id", table_name="finding_selection")
    op.drop_table("finding_selection")
    op.drop_index("ix_finding_objective_analysis", table_name="finding")
    op.drop_index("ix_finding_collection_id", table_name="finding")
    op.drop_table("finding")
