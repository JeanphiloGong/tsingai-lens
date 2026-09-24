"""Persist explicit ObjectiveExperimentSelection links."""

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260924_0067"
down_revision = "20260924_0066"
branch_labels = None
depends_on = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    if "objective_experiment_selection" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "objective_experiment_selection",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("selection_id", sa.String(length=120), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.String(length=120), nullable=False),
        sa.Column("experiment_version", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.BigInteger(), nullable=False),
        sa.Column("outcome", sa.String(length=300), nullable=False),
        sa.Column("missing_context_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("reasons_json", _JSON_DOCUMENT, nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_selection_objective_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["paper_experiment.id"],
            name="fk_selection_paper_experiment_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_objective_experiment_selection"),
        sa.UniqueConstraint("selection_id", name="uq_selection_identity"),
    )
    op.create_index(
        "ix_objective_experiment_selection_collection_id",
        "objective_experiment_selection",
        ["collection_id"],
    )
    op.create_index(
        "ix_objective_experiment_selection_objective_id",
        "objective_experiment_selection",
        ["objective_id"],
    )
    op.create_index(
        "ix_objective_experiment_selection_revision_id",
        "objective_experiment_selection",
        ["revision_id"],
    )

    op.create_table(
        "selection_measurement",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("selection_id", sa.String(length=120), nullable=False),
        sa.Column("revision_id", sa.BigInteger(), nullable=False),
        sa.Column("measurement_id", sa.BigInteger(), nullable=False),
        sa.Column("measurement_key", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["selection_id"],
            ["objective_experiment_selection.selection_id"],
            name="fk_selection_measurement_selection",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "measurement_key"],
            [
                "measurement_result.paper_experiment_id",
                "measurement_result.measurement_key",
            ],
            name="fk_selection_measurement_measurement",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_selection_measurement"),
        sa.UniqueConstraint(
            "selection_id",
            "measurement_key",
            name="uq_selection_measurement_member",
        ),
    )

    op.create_table(
        "selection_comparison",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("selection_id", sa.String(length=120), nullable=False),
        sa.Column("revision_id", sa.BigInteger(), nullable=False),
        sa.Column("comparison_id", sa.BigInteger(), nullable=False),
        sa.Column("comparison_key", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["selection_id"],
            ["objective_experiment_selection.selection_id"],
            name="fk_selection_comparison_selection",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "comparison_key"],
            [
                "experiment_comparison.paper_experiment_id",
                "experiment_comparison.comparison_key",
            ],
            name="fk_selection_comparison_comparison",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_selection_comparison"),
        sa.UniqueConstraint(
            "selection_id",
            "comparison_key",
            name="uq_selection_comparison_member",
        ),
    )


def downgrade():
    op.drop_table("selection_comparison")
    op.drop_table("selection_measurement")
    op.drop_index(
        "ix_objective_experiment_selection_revision_id",
        table_name="objective_experiment_selection",
    )
    op.drop_index(
        "ix_objective_experiment_selection_objective_id",
        table_name="objective_experiment_selection",
    )
    op.drop_index(
        "ix_objective_experiment_selection_collection_id",
        table_name="objective_experiment_selection",
    )
    op.drop_table("objective_experiment_selection")
