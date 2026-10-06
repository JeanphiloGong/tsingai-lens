"""Persist optional cross-paper ComparisonGroups."""

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260924_0068"
down_revision = "20260924_0067"
branch_labels = None
depends_on = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    if "comparison_group" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "comparison_group",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.String(length=120), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=300), nullable=False),
        sa.Column("comparison_target", sa.String(length=40), nullable=False),
        sa.Column("comparison_basis_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("normalizations_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("limitations_json", _JSON_DOCUMENT, nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_comparison_group_objective_analysis",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_comparison_group"),
        sa.UniqueConstraint("group_id", name="uq_comparison_group_identity"),
    )
    op.create_index(
        "ix_comparison_group_collection_id", "comparison_group", ["collection_id"]
    )
    op.create_index(
        "ix_comparison_group_objective_id", "comparison_group", ["objective_id"]
    )

    op.create_table(
        "comparison_group_member",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.String(length=120), nullable=False),
        sa.Column("selection_id", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("comparability", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["comparison_group.group_id"],
            name="fk_comparison_group_member_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["selection_id"],
            ["objective_experiment_selection.selection_id"],
            name="fk_comparison_group_member_selection",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_comparison_group_member"),
        sa.UniqueConstraint(
            "group_id",
            "selection_id",
            name="uq_comparison_group_member_identity",
        ),
    )


def downgrade():
    op.drop_table("comparison_group_member")
    op.drop_index("ix_comparison_group_objective_id", table_name="comparison_group")
    op.drop_index("ix_comparison_group_collection_id", table_name="comparison_group")
    op.drop_table("comparison_group")
