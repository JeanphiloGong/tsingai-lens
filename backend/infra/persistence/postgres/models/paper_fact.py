"""Build-versioned relational document profiles and paper facts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
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


class PaperFactBuild(Base):
    __tablename__ = "paper_fact_builds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_paper_fact_builds_collection_build",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    paper_facts_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class PaperFactDocumentProfile(Base):
    __tablename__ = "paper_fact_document_profiles"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_paper_fact_document_profiles_source_document",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("document_versions.document_version_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    profile_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    parsing_warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class PaperFactEvidenceAnchor(Base):
    __tablename__ = "paper_fact_evidence_anchors"
    __table_args__ = (
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_paper_fact_evidence_anchors_source_document",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    anchor_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("document_versions.document_version_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    anchor_order: Mapped[int] = mapped_column(Integer, nullable=False)
    locator_type: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    section_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_range_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    deep_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    block_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    snippet_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    figure_or_table: Mapped[str | None] = mapped_column(String(), nullable=True)
    quote_span: Mapped[str | None] = mapped_column(Text, nullable=True)


class PaperFactMethod(Base):
    __tablename__ = "paper_fact_methods"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_paper_fact_methods_source_document",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    method_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("document_versions.document_version_id"), nullable=False
    )
    fact_order: Mapped[int] = mapped_column(Integer, nullable=False)
    domain_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    method_role: Mapped[str] = mapped_column(String(128), nullable=False)
    method_name: Mapped[str] = mapped_column(Text, nullable=False)
    method_payload: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)


class PaperFactSampleVariant(Base):
    __tablename__ = "paper_fact_sample_variants"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_paper_fact_sample_variants_source_document",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    variant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("document_versions.document_version_id"), nullable=False
    )
    fact_order: Mapped[int] = mapped_column(Integer, nullable=False)
    domain_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    variant_label: Mapped[str] = mapped_column(Text, nullable=False)
    host_material_system: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    composition: Mapped[str | None] = mapped_column(Text, nullable=True)
    variable_axis_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    variable_value: Mapped[Any | None] = mapped_column(_JSON_DOCUMENT, nullable=True)
    process_context: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    profile_payload: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)


class PaperFactTestCondition(Base):
    __tablename__ = "paper_fact_test_conditions"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_paper_fact_test_conditions_source_document",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    test_condition_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("document_versions.document_version_id"), nullable=False
    )
    fact_order: Mapped[int] = mapped_column(Integer, nullable=False)
    domain_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    property_type: Mapped[str] = mapped_column(String(128), nullable=False)
    template_type: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_level: Mapped[str] = mapped_column(String(64), nullable=False)
    condition_payload: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    condition_completeness: Mapped[str] = mapped_column(String(64), nullable=False)
    missing_fields: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)


class PaperFactBaselineReference(Base):
    __tablename__ = "paper_fact_baseline_references"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_paper_fact_baselines_source_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["build_id", "variant_id"],
            [
                "paper_fact_sample_variants.build_id",
                "paper_fact_sample_variants.variant_id",
            ],
            name="fk_paper_fact_baselines_variant",
            ondelete="RESTRICT",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    baseline_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("document_versions.document_version_id"), nullable=False
    )
    fact_order: Mapped[int] = mapped_column(Integer, nullable=False)
    domain_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    variant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    baseline_type: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_label: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)


class PaperFactCharacterizationObservation(Base):
    __tablename__ = "paper_fact_characterization_observations"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_paper_fact_observations_source_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["build_id", "variant_id"],
            [
                "paper_fact_sample_variants.build_id",
                "paper_fact_sample_variants.variant_id",
            ],
            name="fk_paper_fact_observations_variant",
            ondelete="RESTRICT",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("document_versions.document_version_id"), nullable=False
    )
    fact_order: Mapped[int] = mapped_column(Integer, nullable=False)
    variant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    characterization_type: Mapped[str] = mapped_column(String(128), nullable=False)
    observation_text: Mapped[str] = mapped_column(Text, nullable=False)
    observed_value: Mapped[Any | None] = mapped_column(_JSON_DOCUMENT, nullable=True)
    observed_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    condition_context: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)


class PaperFactStructureFeature(Base):
    __tablename__ = "paper_fact_structure_features"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_paper_fact_features_source_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["build_id", "variant_id"],
            [
                "paper_fact_sample_variants.build_id",
                "paper_fact_sample_variants.variant_id",
            ],
            name="fk_paper_fact_features_variant",
            ondelete="RESTRICT",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    feature_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("document_versions.document_version_id"), nullable=False
    )
    fact_order: Mapped[int] = mapped_column(Integer, nullable=False)
    variant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    feature_type: Mapped[str] = mapped_column(String(128), nullable=False)
    feature_value: Mapped[Any | None] = mapped_column(_JSON_DOCUMENT, nullable=True)
    feature_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    qualitative_descriptor: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)


class PaperFactMeasurementResult(Base):
    __tablename__ = "paper_fact_measurement_results"
    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "build_id",
            "result_id",
            name="uq_paper_fact_results_collection_build_result",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_paper_fact_results_source_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["build_id", "variant_id"],
            [
                "paper_fact_sample_variants.build_id",
                "paper_fact_sample_variants.variant_id",
            ],
            name="fk_paper_fact_results_variant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["build_id", "test_condition_id"],
            [
                "paper_fact_test_conditions.build_id",
                "paper_fact_test_conditions.test_condition_id",
            ],
            name="fk_paper_fact_results_condition",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["build_id", "baseline_id"],
            [
                "paper_fact_baseline_references.build_id",
                "paper_fact_baseline_references.baseline_id",
            ],
            name="fk_paper_fact_results_baseline",
            ondelete="RESTRICT",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("document_versions.document_version_id"), nullable=False
    )
    fact_order: Mapped[int] = mapped_column(Integer, nullable=False)
    domain_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    variant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    property_normalized: Mapped[str] = mapped_column(String(128), nullable=False)
    result_type: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    value_payload: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    test_condition_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    baseline_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    traceability_status: Mapped[str] = mapped_column(String(64), nullable=False)
    result_source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(64), nullable=False)


paper_fact_method_evidence_anchors = Table(
    "paper_fact_method_evidence_anchors",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("method_id", String(128), primary_key=True),
    Column("anchor_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["build_id", "method_id"],
        ["paper_fact_methods.build_id", "paper_fact_methods.method_id"],
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

paper_fact_variant_structure_features = Table(
    "paper_fact_variant_structure_features",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("variant_id", String(128), primary_key=True),
    Column("feature_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["build_id", "variant_id"],
        [
            "paper_fact_sample_variants.build_id",
            "paper_fact_sample_variants.variant_id",
        ],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["build_id", "feature_id"],
        [
            "paper_fact_structure_features.build_id",
            "paper_fact_structure_features.feature_id",
        ],
        ondelete="RESTRICT",
    ),
)

paper_fact_variant_evidence_anchors = Table(
    "paper_fact_variant_evidence_anchors",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("variant_id", String(128), primary_key=True),
    Column("anchor_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["build_id", "variant_id"],
        [
            "paper_fact_sample_variants.build_id",
            "paper_fact_sample_variants.variant_id",
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

paper_fact_condition_evidence_anchors = Table(
    "paper_fact_condition_evidence_anchors",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("test_condition_id", String(128), primary_key=True),
    Column("anchor_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["build_id", "test_condition_id"],
        [
            "paper_fact_test_conditions.build_id",
            "paper_fact_test_conditions.test_condition_id",
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

paper_fact_baseline_evidence_anchors = Table(
    "paper_fact_baseline_evidence_anchors",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("baseline_id", String(128), primary_key=True),
    Column("anchor_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["build_id", "baseline_id"],
        [
            "paper_fact_baseline_references.build_id",
            "paper_fact_baseline_references.baseline_id",
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

paper_fact_observation_evidence_anchors = Table(
    "paper_fact_observation_evidence_anchors",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("observation_id", String(128), primary_key=True),
    Column("anchor_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["build_id", "observation_id"],
        [
            "paper_fact_characterization_observations.build_id",
            "paper_fact_characterization_observations.observation_id",
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

paper_fact_feature_observations = Table(
    "paper_fact_feature_observations",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("feature_id", String(128), primary_key=True),
    Column("observation_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["build_id", "feature_id"],
        [
            "paper_fact_structure_features.build_id",
            "paper_fact_structure_features.feature_id",
        ],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["build_id", "observation_id"],
        [
            "paper_fact_characterization_observations.build_id",
            "paper_fact_characterization_observations.observation_id",
        ],
        ondelete="RESTRICT",
    ),
)

paper_fact_result_structure_features = Table(
    "paper_fact_result_structure_features",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("result_id", String(128), primary_key=True),
    Column("feature_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["build_id", "result_id"],
        [
            "paper_fact_measurement_results.build_id",
            "paper_fact_measurement_results.result_id",
        ],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["build_id", "feature_id"],
        [
            "paper_fact_structure_features.build_id",
            "paper_fact_structure_features.feature_id",
        ],
        ondelete="RESTRICT",
    ),
)

paper_fact_result_observations = Table(
    "paper_fact_result_observations",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("result_id", String(128), primary_key=True),
    Column("observation_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["build_id", "result_id"],
        [
            "paper_fact_measurement_results.build_id",
            "paper_fact_measurement_results.result_id",
        ],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["build_id", "observation_id"],
        [
            "paper_fact_characterization_observations.build_id",
            "paper_fact_characterization_observations.observation_id",
        ],
        ondelete="RESTRICT",
    ),
)

paper_fact_result_evidence_anchors = Table(
    "paper_fact_result_evidence_anchors",
    Base.metadata,
    Column("build_id", String(64), primary_key=True),
    Column("result_id", String(128), primary_key=True),
    Column("anchor_id", String(128), primary_key=True),
    Column("position", Integer, nullable=False),
    ForeignKeyConstraint(
        ["build_id", "result_id"],
        [
            "paper_fact_measurement_results.build_id",
            "paper_fact_measurement_results.result_id",
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
    "PaperFactBaselineReference",
    "PaperFactBuild",
    "PaperFactCharacterizationObservation",
    "PaperFactDocumentProfile",
    "PaperFactEvidenceAnchor",
    "PaperFactMeasurementResult",
    "PaperFactMethod",
    "PaperFactSampleVariant",
    "PaperFactStructureFeature",
    "PaperFactTestCondition",
    "paper_fact_baseline_evidence_anchors",
    "paper_fact_condition_evidence_anchors",
    "paper_fact_feature_observations",
    "paper_fact_method_evidence_anchors",
    "paper_fact_observation_evidence_anchors",
    "paper_fact_result_evidence_anchors",
    "paper_fact_result_observations",
    "paper_fact_result_structure_features",
    "paper_fact_variant_evidence_anchors",
    "paper_fact_variant_structure_features",
]
