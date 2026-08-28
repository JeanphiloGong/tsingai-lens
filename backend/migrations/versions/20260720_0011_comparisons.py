"""Add build-versioned comparison semantics

Revision ID: 20260720_0011
Revises: 20260719_0010
Create Date: 2026-07-20 10:00:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260720_0011"
down_revision: Union[str, Sequence[str], None] = "20260719_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("paper_fact_measurement_results") as batch_op:
        batch_op.create_unique_constraint(
            "uq_paper_fact_results_collection_build_result",
            ["collection_id", "build_id", "result_id"],
        )

    op.create_table(
        "comparison_builds",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("comparison_artifacts_ready", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_comparison_builds_collection_build",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("build_id", name=op.f("pk_comparison_builds")),
        sa.UniqueConstraint(
            "collection_id", "build_id", name="uq_comparison_builds_collection_build"
        ),
    )
    op.create_index(
        op.f("ix_comparison_builds_collection_id"),
        "comparison_builds",
        ["collection_id"],
        unique=False,
    )
    op.create_table(
        "comparable_results",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("comparable_result_id", sa.String(length=160), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("result_order", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("paper_result_id", sa.String(length=128), nullable=True),
        sa.Column("objective_evidence_unit_id", sa.String(length=128), nullable=True),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("variant_id", sa.String(length=128), nullable=True),
        sa.Column("baseline_id", sa.String(length=128), nullable=True),
        sa.Column("test_condition_id", sa.String(length=128), nullable=True),
        sa.Column("material_system_normalized", sa.Text(), nullable=False),
        sa.Column("process_normalized", sa.Text(), nullable=True),
        sa.Column("baseline_normalized", sa.Text(), nullable=True),
        sa.Column("test_condition_normalized", sa.Text(), nullable=True),
        sa.Column("axis_name", sa.Text(), nullable=True),
        sa.Column("axis_value", JSON_DOCUMENT, nullable=True),
        sa.Column("axis_unit", sa.String(length=64), nullable=True),
        sa.Column("property_normalized", sa.Text(), nullable=False),
        sa.Column("result_type", sa.String(length=64), nullable=False),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("statistic_type", sa.String(length=64), nullable=True),
        sa.Column("uncertainty", sa.Text(), nullable=True),
        sa.Column("traceability_status", sa.String(length=64), nullable=False),
        sa.Column("variant_label", sa.Text(), nullable=True),
        sa.Column("baseline_reference", sa.Text(), nullable=True),
        sa.Column("result_source_type", sa.String(length=64), nullable=True),
        sa.Column("epistemic_status", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "(source_kind = 'paper_measurement' AND paper_result_id IS NOT NULL "
            "AND objective_evidence_unit_id IS NULL) OR "
            "(source_kind = 'objective_evidence_unit' "
            "AND paper_result_id IS NULL AND objective_evidence_unit_id IS NOT NULL)",
            name=op.f("ck_comparable_results_typed_source_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["comparison_builds.collection_id", "comparison_builds.build_id"],
            name="fk_comparable_results_build",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "objective_evidence_unit_id"],
            [
                "objective_evidence_units.collection_id",
                "objective_evidence_units.build_id",
                "objective_evidence_units.evidence_unit_id",
            ],
            name="fk_comparable_results_objective_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "paper_result_id"],
            [
                "paper_fact_measurement_results.collection_id",
                "paper_fact_measurement_results.build_id",
                "paper_fact_measurement_results.result_id",
            ],
            name="fk_comparable_results_paper_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_comparable_results_source_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "build_id", "comparable_result_id", name=op.f("pk_comparable_results")
        ),
    )
    op.create_index(
        op.f("ix_comparable_results_collection_id"),
        "comparable_results",
        ["collection_id"],
        unique=False,
    )
    op.create_table(
        "collection_comparable_results",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("comparable_result_id", sa.String(length=160), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("missing_critical_context", JSON_DOCUMENT, nullable=False),
        sa.Column("comparability_basis", JSON_DOCUMENT, nullable=False),
        sa.Column("comparability_warnings", JSON_DOCUMENT, nullable=False),
        sa.Column("comparability_status", sa.String(length=64), nullable=False),
        sa.Column("requires_expert_review", sa.Boolean(), nullable=False),
        sa.Column("assessment_epistemic_status", sa.String(length=64), nullable=False),
        sa.Column("epistemic_status", sa.String(length=64), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("policy_family", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column(
            "comparable_result_normalization_version",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("assessment_input_fingerprint", sa.Text(), nullable=False),
        sa.Column("reassessment_triggers", JSON_DOCUMENT, nullable=False),
        sa.CheckConstraint(
            "sort_order IS NULL OR sort_order >= 0",
            name=op.f("ck_collection_comparable_results_sort_order_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["comparison_builds.collection_id", "comparison_builds.build_id"],
            name="fk_collection_comparable_results_build",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "comparable_result_id"],
            ["comparable_results.build_id", "comparable_results.comparable_result_id"],
            name="fk_collection_comparable_results_result",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "comparable_result_id",
            name=op.f("pk_collection_comparable_results"),
        ),
    )
    op.create_index(
        op.f("ix_collection_comparable_results_collection_id"),
        "collection_comparable_results",
        ["collection_id"],
        unique=False,
    )
    op.create_table(
        "pairwise_comparison_relations",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("relation_id", sa.String(length=160), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("relation_order", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.String(length=128), nullable=False),
        sa.Column("current_variant_id", sa.String(length=128), nullable=False),
        sa.Column("reference_variant_id", sa.String(length=128), nullable=False),
        sa.Column("comparison_axis", sa.Text(), nullable=False),
        sa.Column("property_normalized", sa.Text(), nullable=False),
        sa.Column("current_result_id", sa.String(length=128), nullable=False),
        sa.Column("reference_result_id", sa.String(length=128), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=True),
        sa.Column("reference_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("direction", sa.String(length=64), nullable=False),
        sa.Column("relation_payload", JSON_DOCUMENT, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("epistemic_status", sa.String(length=64), nullable=False),
        sa.Column("relation_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_pairwise_comparison_relations_confidence_range"),
        ),
        sa.CheckConstraint(
            "current_result_id <> reference_result_id",
            name=op.f("ck_pairwise_comparison_relations_distinct_results"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["comparison_builds.collection_id", "comparison_builds.build_id"],
            name="fk_pairwise_relations_build",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "current_result_id"],
            [
                "paper_fact_measurement_results.build_id",
                "paper_fact_measurement_results.result_id",
            ],
            name="fk_pairwise_relations_current_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "current_variant_id"],
            [
                "paper_fact_sample_variants.build_id",
                "paper_fact_sample_variants.variant_id",
            ],
            name="fk_pairwise_relations_current_variant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "reference_result_id"],
            [
                "paper_fact_measurement_results.build_id",
                "paper_fact_measurement_results.result_id",
            ],
            name="fk_pairwise_relations_reference_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "reference_variant_id"],
            [
                "paper_fact_sample_variants.build_id",
                "paper_fact_sample_variants.variant_id",
            ],
            name="fk_pairwise_relations_reference_variant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_pairwise_relations_source_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "build_id", "relation_id", name=op.f("pk_pairwise_comparison_relations")
        ),
    )
    op.create_index(
        op.f("ix_pairwise_comparison_relations_collection_id"),
        "pairwise_comparison_relations",
        ["collection_id"],
        unique=False,
    )
    op.create_table(
        "comparable_result_anchor_links",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("comparable_result_id", sa.String(length=160), nullable=False),
        sa.Column("link_kind", sa.String(length=16), nullable=False),
        sa.Column("anchor_id", sa.String(length=128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "link_kind IN ('direct', 'contextual')",
            name=op.f("ck_comparable_result_anchor_links_link_kind_valid"),
        ),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_comparable_result_anchor_links_position_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "anchor_id"],
            [
                "paper_fact_evidence_anchors.build_id",
                "paper_fact_evidence_anchors.anchor_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "comparable_result_id"],
            ["comparable_results.build_id", "comparable_results.comparable_result_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "comparable_result_id",
            "link_kind",
            "anchor_id",
            name=op.f("pk_comparable_result_anchor_links"),
        ),
        sa.UniqueConstraint(
            "build_id",
            "comparable_result_id",
            "link_kind",
            "position",
            name="uq_comparable_result_anchor_links_position",
        ),
    )
    _create_result_link_table("comparable_result_evidence_links", "evidence_id", 160)
    _create_result_link_table(
        "comparable_result_feature_links",
        "feature_id",
        128,
        "paper_fact_structure_features",
    )
    _create_result_link_table(
        "comparable_result_observation_links",
        "observation_id",
        128,
        "paper_fact_characterization_observations",
    )
    op.create_table(
        "pairwise_comparison_anchor_links",
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("relation_id", sa.String(length=160), nullable=False),
        sa.Column("anchor_id", sa.String(length=128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_pairwise_comparison_anchor_links_position_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "anchor_id"],
            [
                "paper_fact_evidence_anchors.build_id",
                "paper_fact_evidence_anchors.anchor_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "relation_id"],
            [
                "pairwise_comparison_relations.build_id",
                "pairwise_comparison_relations.relation_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "relation_id",
            "anchor_id",
            name=op.f("pk_pairwise_comparison_anchor_links"),
        ),
        sa.UniqueConstraint(
            "build_id",
            "relation_id",
            "position",
            name="uq_pairwise_anchor_links_position",
        ),
    )


def _create_result_link_table(
    table_name: str,
    value_column: str,
    value_length: int,
    target_table: str | None = None,
) -> None:
    constraints: list[sa.SchemaItem] = [
        sa.CheckConstraint(
            "position >= 0", name=op.f(f"ck_{table_name}_position_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "comparable_result_id"],
            ["comparable_results.build_id", "comparable_results.comparable_result_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "build_id",
            "comparable_result_id",
            value_column,
            name=op.f(f"pk_{table_name}"),
        ),
        sa.UniqueConstraint(
            "build_id",
            "comparable_result_id",
            "position",
            name=f"uq_{table_name}_position",
        ),
    ]
    if target_table:
        constraints.append(
            sa.ForeignKeyConstraint(
                ["build_id", value_column],
                [f"{target_table}.build_id", f"{target_table}.{value_column}"],
                ondelete="RESTRICT",
            )
        )
    op.create_table(
        table_name,
        sa.Column("build_id", sa.String(length=64), nullable=False),
        sa.Column("comparable_result_id", sa.String(length=160), nullable=False),
        sa.Column(value_column, sa.String(length=value_length), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *constraints,
    )


def downgrade() -> None:
    op.drop_table("pairwise_comparison_anchor_links")
    op.drop_table("comparable_result_observation_links")
    op.drop_table("comparable_result_feature_links")
    op.drop_table("comparable_result_evidence_links")
    op.drop_table("comparable_result_anchor_links")
    op.drop_index(
        op.f("ix_pairwise_comparison_relations_collection_id"),
        table_name="pairwise_comparison_relations",
    )
    op.drop_table("pairwise_comparison_relations")
    op.drop_index(
        op.f("ix_collection_comparable_results_collection_id"),
        table_name="collection_comparable_results",
    )
    op.drop_table("collection_comparable_results")
    op.drop_index(
        op.f("ix_comparable_results_collection_id"),
        table_name="comparable_results",
    )
    op.drop_table("comparable_results")
    op.drop_index(
        op.f("ix_comparison_builds_collection_id"),
        table_name="comparison_builds",
    )
    op.drop_table("comparison_builds")
    with op.batch_alter_table("paper_fact_measurement_results") as batch_op:
        batch_op.drop_constraint(
            "uq_paper_fact_results_collection_build_result", type_="unique"
        )
