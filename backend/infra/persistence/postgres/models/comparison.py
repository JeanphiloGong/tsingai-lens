"""Build-versioned comparison semantics and collection assessments."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKeyConstraint,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ComparisonBuild(Base):
    __tablename__ = "comparison_builds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_comparison_builds_collection_build",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id", "build_id", name="uq_comparison_builds_collection_build"
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    comparison_artifacts_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ComparableResultRecord(Base):
    __tablename__ = "comparable_results"
    __table_args__ = (
        CheckConstraint(
            "source_kind = 'paper_measurement' AND paper_result_id IS NOT NULL",
            name="typed_source_valid",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["comparison_builds.collection_id", "comparison_builds.build_id"],
            name="fk_comparable_results_build",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_comparable_results_source_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "paper_result_id"],
            [
                "paper_fact_measurement_results.collection_id",
                "paper_fact_measurement_results.build_id",
                "paper_fact_measurement_results.result_id",
            ],
            name="fk_comparable_results_paper_result",
            ondelete="RESTRICT",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    comparable_result_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    paper_result_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    variant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    baseline_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    test_condition_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    material_system_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    process_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_condition_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    axis_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    axis_value: Mapped[Any | None] = mapped_column(_JSON_DOCUMENT, nullable=True)
    axis_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    property_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    result_type: Mapped[str] = mapped_column(String(64), nullable=False)
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    statistic_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uncertainty: Mapped[str | None] = mapped_column(Text, nullable=True)
    traceability_status: Mapped[str] = mapped_column(String(64), nullable=False)
    variant_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)


class CollectionComparableResultRecord(Base):
    __tablename__ = "collection_comparable_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["comparison_builds.collection_id", "comparison_builds.build_id"],
            name="fk_collection_comparable_results_build",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["build_id", "comparable_result_id"],
            ["comparable_results.build_id", "comparable_results.comparable_result_id"],
            name="fk_collection_comparable_results_result",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "sort_order IS NULL OR sort_order >= 0", name="sort_order_valid"
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    comparable_result_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    missing_critical_context: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    comparability_basis: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    comparability_warnings: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    comparability_status: Mapped[str] = mapped_column(String(64), nullable=False)
    requires_expert_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    assessment_epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_family: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    comparable_result_normalization_version: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    assessment_input_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    reassessment_triggers: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


def _ordered_result_link_table(
    table_name: str,
    value_name: str,
    value_length: int,
    target_table: str | None = None,
    target_column: str | None = None,
) -> Table:
    constraints = [
        CheckConstraint("position >= 0", name="position_non_negative"),
        ForeignKeyConstraint(
            ["build_id", "comparable_result_id"],
            ["comparable_results.build_id", "comparable_results.comparable_result_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "build_id",
            "comparable_result_id",
            "position",
            name=f"uq_{table_name}_position",
        ),
    ]
    if target_table and target_column:
        constraints.append(
            ForeignKeyConstraint(
                ["build_id", value_name],
                [f"{target_table}.build_id", f"{target_table}.{target_column}"],
                ondelete="RESTRICT",
            )
        )
    return Table(
        table_name,
        Base.metadata,
        Column("build_id", String(64), primary_key=True),
        Column("comparable_result_id", String(160), primary_key=True),
        Column(value_name, String(value_length), primary_key=True),
        Column("position", Integer, nullable=False),
        *constraints,
    )


comparable_result_evidence_links = _ordered_result_link_table(
    "comparable_result_evidence_links", "evidence_id", 160
)

comparable_result_feature_links = _ordered_result_link_table(
    "comparable_result_feature_links",
    "feature_id",
    128,
    "paper_fact_structure_features",
    "feature_id",
)

comparable_result_observation_links = _ordered_result_link_table(
    "comparable_result_observation_links",
    "observation_id",
    128,
    "paper_fact_characterization_observations",
    "observation_id",
)


comparable_result_anchor_links = Table(
    "comparable_result_anchor_links",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("comparable_result_id", String(160), primary_key=True),
    Column("link_kind", String(16), primary_key=True),
    Column("anchor_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    CheckConstraint("link_kind IN ('direct', 'contextual')", name="link_kind_valid"),
    CheckConstraint("position >= 0", name="position_non_negative"),
    UniqueConstraint(
        "build_id",
        "comparable_result_id",
        "link_kind",
        "position",
        name="uq_comparable_result_anchor_links_position",
    ),
    ForeignKeyConstraint(
        ["build_id", "comparable_result_id"],
        ["comparable_results.build_id", "comparable_results.comparable_result_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["build_id", "anchor_id"],
        [
            "paper_fact_evidence_anchors.build_id",
            "paper_fact_evidence_anchors.anchor_id",
        ],
        ondelete="RESTRICT",
    ),
)


class PairwiseComparisonRelationRecord(Base):
    __tablename__ = "pairwise_comparison_relations"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "current_result_id <> reference_result_id", name="distinct_results"
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["comparison_builds.collection_id", "comparison_builds.build_id"],
            name="fk_pairwise_relations_build",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_pairwise_relations_source_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["build_id", "current_result_id"],
            [
                "paper_fact_measurement_results.build_id",
                "paper_fact_measurement_results.result_id",
            ],
            name="fk_pairwise_relations_current_result",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["build_id", "reference_result_id"],
            [
                "paper_fact_measurement_results.build_id",
                "paper_fact_measurement_results.result_id",
            ],
            name="fk_pairwise_relations_reference_result",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["build_id", "current_variant_id"],
            [
                "paper_fact_sample_variants.build_id",
                "paper_fact_sample_variants.variant_id",
            ],
            name="fk_pairwise_relations_current_variant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["build_id", "reference_variant_id"],
            [
                "paper_fact_sample_variants.build_id",
                "paper_fact_sample_variants.variant_id",
            ],
            name="fk_pairwise_relations_reference_variant",
            ondelete="RESTRICT",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    relation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    relation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    current_variant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_variant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    comparison_axis: Mapped[str] = mapped_column(Text, nullable=False)
    property_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    current_result_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_result_id: Mapped[str] = mapped_column(String(128), nullable=False)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    direction: Mapped[str] = mapped_column(String(64), nullable=False)
    relation_payload: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)
    relation_version: Mapped[str] = mapped_column(String(64), nullable=False)


pairwise_comparison_anchor_links = Table(
    "pairwise_comparison_anchor_links",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("relation_id", String(160), primary_key=True),
    Column("anchor_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    CheckConstraint("position >= 0", name="position_non_negative"),
    UniqueConstraint(
        "build_id", "relation_id", "position", name="uq_pairwise_anchor_links_position"
    ),
    ForeignKeyConstraint(
        ["build_id", "relation_id"],
        [
            "pairwise_comparison_relations.build_id",
            "pairwise_comparison_relations.relation_id",
        ],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["build_id", "anchor_id"],
        [
            "paper_fact_evidence_anchors.build_id",
            "paper_fact_evidence_anchors.anchor_id",
        ],
        ondelete="RESTRICT",
    ),
)


__all__ = [
    "CollectionComparableResultRecord",
    "ComparableResultRecord",
    "ComparisonBuild",
    "PairwiseComparisonRelationRecord",
    "comparable_result_anchor_links",
    "comparable_result_evidence_links",
    "comparable_result_feature_links",
    "comparable_result_observation_links",
    "pairwise_comparison_anchor_links",
]
