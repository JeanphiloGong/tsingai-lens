"""Versioned PaperExperiment records and their revision-local components."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class PaperExperimentRow(Base):
    """One immutable version of a reusable paper experiment."""

    __tablename__ = "paper_experiment"
    __table_args__ = (
        CheckConstraint("experiment_version >= 1", name="version_positive"),
        CheckConstraint(
            "design_type IN ('parallel', 'factorial', 'dose_response', "
            "'observational', 'unknown')",
            name="design_type_valid",
        ),
        CheckConstraint(
            "identity_status IN ('identified', 'partial', 'unknown')",
            name="identity_status_valid",
        ),
        CheckConstraint(
            "binding_status IN ('draft', 'partial', 'bound')",
            name="binding_status_valid",
        ),
        UniqueConstraint(
            "experiment_id",
            "experiment_version",
            name="uq_paper_experiment_identity_version",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    experiment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_fingerprint: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    scope_description: Mapped[str] = mapped_column(Text, nullable=False)
    design_type: Mapped[str] = mapped_column(String(40), nullable=False)
    identity_status: Mapped[str] = mapped_column(String(20), nullable=False)
    binding_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    unresolved_issues_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ExperimentalVariantRow(Base):
    __tablename__ = "experimental_variant"
    __table_args__ = (
        CheckConstraint(
            "binding_status IN ('direct', 'derived', 'uncertain', 'conflict')",
            name="binding_status_valid",
        ),
        UniqueConstraint(
            "paper_experiment_id",
            "variant_key",
            name="uq_experimental_variant_revision_key",
        ),
        UniqueConstraint(
            "paper_experiment_id",
            "position",
            name="uq_experimental_variant_revision_position",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paper_experiment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("paper_experiment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    variant_key: Mapped[str] = mapped_column(String(100), nullable=False)
    variant_label: Mapped[str] = mapped_column(String(300), nullable=False)
    subject_attributes_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    intervention_attributes_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    state_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    population_scope_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    binding_source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    binding_status: Mapped[str] = mapped_column(String(20), nullable=False)
    notes_json: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ExperimentTestConditionRow(Base):
    __tablename__ = "test_condition"
    __table_args__ = (
        CheckConstraint(
            "binding_status IN ('direct', 'derived', 'uncertain', 'conflict')",
            name="binding_status_valid",
        ),
        UniqueConstraint(
            "paper_experiment_id",
            "test_key",
            name="uq_test_condition_revision_key",
        ),
        UniqueConstraint(
            "paper_experiment_id",
            "position",
            name="uq_test_condition_revision_position",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paper_experiment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("paper_experiment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    test_key: Mapped[str] = mapped_column(String(100), nullable=False)
    test_type: Mapped[str] = mapped_column(String(200), nullable=False)
    parameters_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    population_scope_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    binding_status: Mapped[str] = mapped_column(String(20), nullable=False)
    notes_json: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ExperimentMeasurementResultRow(Base):
    __tablename__ = "measurement_result"
    __table_args__ = (
        CheckConstraint(
            "value_numeric IS NOT NULL OR value_text IS NOT NULL "
            "OR result_text IS NOT NULL",
            name="value_present",
        ),
        CheckConstraint(
            "result_kind IN ('measured', 'observed', 'simulated', 'predicted', "
            "'unknown')",
            name="result_kind_valid",
        ),
        CheckConstraint(
            "binding_status IN ('direct', 'derived', 'uncertain', 'conflict')",
            name="binding_status_valid",
        ),
        UniqueConstraint(
            "paper_experiment_id",
            "measurement_key",
            name="uq_measurement_result_revision_key",
        ),
        UniqueConstraint(
            "paper_experiment_id",
            "position",
            name="uq_measurement_result_revision_position",
        ),
        ForeignKeyConstraint(
            ["paper_experiment_id", "variant_key"],
            [
                "experimental_variant.paper_experiment_id",
                "experimental_variant.variant_key",
            ],
            name="fk_measurement_result_revision_variant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["paper_experiment_id", "test_key"],
            ["test_condition.paper_experiment_id", "test_condition.test_key"],
            name="fk_measurement_result_revision_test",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paper_experiment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("paper_experiment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    measurement_key: Mapped[str] = mapped_column(String(100), nullable=False)
    variant_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    test_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outcome: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    statistics_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    measurement_scope_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    result_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    binding_source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    binding_status: Mapped[str] = mapped_column(String(20), nullable=False)
    notes_json: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ExperimentComparisonRow(Base):
    __tablename__ = "experiment_comparison"
    __table_args__ = (
        CheckConstraint("basis IN ('reported', 'derived')", name="basis_valid"),
        CheckConstraint(
            "direction IN ('increase', 'decrease', 'no_change', 'mixed', 'unknown')",
            name="direction_valid",
        ),
        CheckConstraint(
            "status IN ('ready', 'insufficient_context', 'non_comparable')",
            name="status_valid",
        ),
        CheckConstraint(
            "relation_status IN ('direct', 'derived', 'uncertain', 'conflict')",
            name="relation_status_valid",
        ),
        UniqueConstraint(
            "paper_experiment_id",
            "comparison_key",
            name="uq_experiment_comparison_revision_key",
        ),
        UniqueConstraint(
            "paper_experiment_id",
            "position",
            name="uq_experiment_comparison_revision_position",
        ),
        ForeignKeyConstraint(
            ["paper_experiment_id", "baseline_variant_key"],
            [
                "experimental_variant.paper_experiment_id",
                "experimental_variant.variant_key",
            ],
            name="fk_experiment_comparison_revision_baseline_variant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["paper_experiment_id", "target_variant_key"],
            [
                "experimental_variant.paper_experiment_id",
                "experimental_variant.variant_key",
            ],
            name="fk_experiment_comparison_revision_target_variant",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paper_experiment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("paper_experiment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_key: Mapped[str] = mapped_column(String(100), nullable=False)
    baseline_variant_key: Mapped[str] = mapped_column(String(100), nullable=False)
    target_variant_key: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(300), nullable=False)
    changed_variables_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    matched_conditions_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    basis: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    reported_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribution_scope: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reasons_json: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    binding_source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    relation_status: Mapped[str] = mapped_column(String(20), nullable=False)


class ExperimentComparisonMeasurementRow(Base):
    __tablename__ = "experiment_comparison_measurement"
    __table_args__ = (
        CheckConstraint("side IN ('baseline', 'target')", name="side_valid"),
        UniqueConstraint(
            "paper_experiment_id",
            "comparison_key",
            "side",
            "position",
            name="uq_experiment_comparison_measurement_position",
        ),
        UniqueConstraint(
            "paper_experiment_id",
            "comparison_key",
            "side",
            "measurement_key",
            name="uq_experiment_comparison_measurement_member",
        ),
        ForeignKeyConstraint(
            ["paper_experiment_id", "comparison_key"],
            [
                "experiment_comparison.paper_experiment_id",
                "experiment_comparison.comparison_key",
            ],
            name="fk_experiment_comparison_measurement_comparison",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["paper_experiment_id", "measurement_key"],
            [
                "measurement_result.paper_experiment_id",
                "measurement_result.measurement_key",
            ],
            name="fk_experiment_comparison_measurement_measurement",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paper_experiment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "paper_experiment.id",
            name="fk_experiment_comparison_measurement_experiment",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    comparison_key: Mapped[str] = mapped_column(String(100), nullable=False)
    side: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    measurement_key: Mapped[str] = mapped_column(String(100), nullable=False)


class ReportedInterpretationRow(Base):
    __tablename__ = "reported_interpretation"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('result_summary', 'mechanism_hypothesis', 'limitation')",
            name="kind_valid",
        ),
        UniqueConstraint(
            "paper_experiment_id",
            "position",
            name="uq_reported_interpretation_revision_position",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paper_experiment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("paper_experiment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    measurement_keys_json: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    comparison_keys_json: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


__all__ = [
    "ExperimentComparisonMeasurementRow",
    "ExperimentComparisonRow",
    "ExperimentMeasurementResultRow",
    "ExperimentTestConditionRow",
    "ExperimentalVariantRow",
    "PaperExperimentRow",
    "ReportedInterpretationRow",
]
