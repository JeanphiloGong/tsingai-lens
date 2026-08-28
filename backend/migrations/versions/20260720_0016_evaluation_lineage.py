"""Persist evaluation lineage in PostgreSQL.

Revision ID: 20260720_0016
Revises: 20260720_0015
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260720_0016"
down_revision: str | Sequence[str] | None = "20260720_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "evaluation_gold_sets",
        sa.Column("gold_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("target_layer", sa.String(length=32), nullable=False),
        sa.Column("metric_profile", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", _JSON_DOCUMENT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_evaluation_gold_sets_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("gold_id", name=op.f("pk_evaluation_gold_sets")),
    )
    op.create_index(
        op.f("ix_evaluation_gold_sets_collection_id"),
        "evaluation_gold_sets",
        ["collection_id"],
        unique=False,
    )
    op.create_table(
        "evaluation_prediction_snapshots",
        sa.Column("snapshot_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("target_layer", sa.String(length=32), nullable=False),
        sa.Column("fact_source", sa.String(length=64), nullable=False),
        sa.Column("system_context", _JSON_DOCUMENT, nullable=False),
        sa.Column("artifact_counts", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_evaluation_prediction_snapshots_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "snapshot_id",
            name=op.f("pk_evaluation_prediction_snapshots"),
        ),
    )
    op.create_index(
        "ix_evaluation_snapshots_collection",
        "evaluation_prediction_snapshots",
        ["collection_id", "fact_source"],
        unique=False,
    )
    op.create_table(
        "evaluation_gold_items",
        sa.Column("gold_item_id", sa.String(length=128), nullable=False),
        sa.Column("gold_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("family", sa.String(length=128), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("payload", _JSON_DOCUMENT, nullable=False),
        sa.Column("evidence_refs", _JSON_DOCUMENT, nullable=False),
        sa.Column("metadata_json", _JSON_DOCUMENT, nullable=False),
        sa.ForeignKeyConstraint(
            ["gold_id"],
            ["evaluation_gold_sets.gold_id"],
            name=op.f("fk_evaluation_gold_items_gold_id_evaluation_gold_sets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("gold_item_id", name=op.f("pk_evaluation_gold_items")),
    )
    op.create_index(
        "ix_evaluation_gold_items_gold_family",
        "evaluation_gold_items",
        ["gold_id", "family", "document_id"],
        unique=False,
    )
    op.create_table(
        "evaluation_prediction_items",
        sa.Column("snapshot_id", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("family", sa.String(length=128), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("payload", _JSON_DOCUMENT, nullable=False),
        sa.Column("source_refs", _JSON_DOCUMENT, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["evaluation_prediction_snapshots.snapshot_id"],
            name=op.f(
                "fk_evaluation_prediction_items_snapshot_id_evaluation_prediction_snapshots"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "snapshot_id",
            "item_id",
            name=op.f("pk_evaluation_prediction_items"),
        ),
    )
    op.create_index(
        "ix_evaluation_prediction_items_family",
        "evaluation_prediction_items",
        ["snapshot_id", "family", "document_id"],
        unique=False,
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("evaluation_run_id", sa.String(length=128), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("gold_id", sa.String(length=128), nullable=False),
        sa.Column("prediction_snapshot_id", sa.String(length=128), nullable=False),
        sa.Column("target_layer", sa.String(length=32), nullable=False),
        sa.Column("fact_source", sa.String(length=64), nullable=False),
        sa.Column("metric_profile", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("summary", _JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_evaluation_runs_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["gold_id"],
            ["evaluation_gold_sets.gold_id"],
            name=op.f("fk_evaluation_runs_gold_id_evaluation_gold_sets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prediction_snapshot_id"],
            ["evaluation_prediction_snapshots.snapshot_id"],
            name=op.f(
                "fk_evaluation_runs_prediction_snapshot_id_evaluation_prediction_snapshots"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evaluation_run_id", name=op.f("pk_evaluation_runs")),
    )
    op.create_index(
        "ix_evaluation_runs_collection",
        "evaluation_runs",
        ["collection_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "evaluation_scores",
        sa.Column("score_id", sa.String(length=128), nullable=False),
        sa.Column("evaluation_run_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=True),
        sa.Column("family", sa.String(length=128), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("numerator", sa.Float(), nullable=True),
        sa.Column("denominator", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.evaluation_run_id"],
            name=op.f("fk_evaluation_scores_evaluation_run_id_evaluation_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("score_id", name=op.f("pk_evaluation_scores")),
    )
    op.create_index(
        op.f("ix_evaluation_scores_evaluation_run_id"),
        "evaluation_scores",
        ["evaluation_run_id"],
        unique=False,
    )
    op.create_table(
        "evaluation_failures",
        sa.Column("failure_id", sa.String(length=128), nullable=False),
        sa.Column("evaluation_run_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("family", sa.String(length=128), nullable=False),
        sa.Column("failure_type", sa.String(length=64), nullable=False),
        sa.Column("likely_layer", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("gold_item_id", sa.String(length=128), nullable=True),
        sa.Column("prediction_item_id", sa.String(length=128), nullable=True),
        sa.Column("gold", _JSON_DOCUMENT, nullable=True),
        sa.Column("prediction", _JSON_DOCUMENT, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source_refs", _JSON_DOCUMENT, nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.evaluation_run_id"],
            name=op.f("fk_evaluation_failures_evaluation_run_id_evaluation_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("failure_id", name=op.f("pk_evaluation_failures")),
    )
    op.create_index(
        "ix_evaluation_failures_family",
        "evaluation_failures",
        ["evaluation_run_id", "family", "failure_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_failures_family", table_name="evaluation_failures")
    op.drop_table("evaluation_failures")
    op.drop_index(
        op.f("ix_evaluation_scores_evaluation_run_id"),
        table_name="evaluation_scores",
    )
    op.drop_table("evaluation_scores")
    op.drop_index("ix_evaluation_runs_collection", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    op.drop_index(
        "ix_evaluation_prediction_items_family",
        table_name="evaluation_prediction_items",
    )
    op.drop_table("evaluation_prediction_items")
    op.drop_index(
        "ix_evaluation_gold_items_gold_family",
        table_name="evaluation_gold_items",
    )
    op.drop_table("evaluation_gold_items")
    op.drop_index(
        "ix_evaluation_snapshots_collection",
        table_name="evaluation_prediction_snapshots",
    )
    op.drop_table("evaluation_prediction_snapshots")
    op.drop_index(
        op.f("ix_evaluation_gold_sets_collection_id"),
        table_name="evaluation_gold_sets",
    )
    op.drop_table("evaluation_gold_sets")
