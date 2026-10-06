"""Persist Findings as references to selections and optional groups."""

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260924_0070"
down_revision = "20260924_0069"
branch_labels = None
depends_on = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    if "finding" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "finding",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("finding_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("factors_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("outcome", sa.String(length=300), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("assertion_strength", sa.String(length=20), nullable=False),
        sa.Column("attribution_scope", sa.String(length=30), nullable=False),
        sa.Column("synthesis_status", sa.String(length=40), nullable=False),
        sa.Column("certainty", sa.Float(), nullable=False),
        sa.Column("display_rank", sa.Integer(), nullable=False),
        sa.Column("mechanisms_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("scientific_context_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("limitations_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("source_analysis_version", sa.Integer(), nullable=True),
        sa.Column("parent_finding_id", sa.String(length=128), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=128), nullable=True),
        sa.Column("created_by_tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warnings_json", _JSON_DOCUMENT, nullable=False),
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


def _drop_index_if_present(name: str, table_name: str) -> None:
    inspector = inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return
    if name in {item["name"] for item in inspector.get_indexes(table_name)}:
        op.drop_index(name, table_name=table_name)


def _drop_table_if_present(table_name: str) -> None:
    if table_name in inspect(op.get_bind()).get_table_names():
        op.drop_table(table_name)


def downgrade():
    _drop_index_if_present(
        "ix_finding_comparison_group_group_id",
        table_name="finding_comparison_group",
    )
    _drop_table_if_present("finding_comparison_group")
    _drop_index_if_present("ix_finding_selection_selection_id", table_name="finding_selection")
    _drop_table_if_present("finding_selection")
    _drop_index_if_present("ix_finding_objective_analysis", table_name="finding")
    _drop_index_if_present("ix_finding_collection_id", table_name="finding")
    _drop_table_if_present("finding")
