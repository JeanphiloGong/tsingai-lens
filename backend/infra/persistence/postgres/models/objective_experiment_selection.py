"""Persistence for ObjectiveExperimentSelection and its explicit links."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    ForeignKeyConstraint,
    JSON,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ObjectiveExperimentSelectionRow(Base):
    __tablename__ = "objective_experiment_selection"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_selection_objective_analysis",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["revision_id"],
            ["paper_experiment.id"],
            name="fk_selection_paper_experiment_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("selection_id", name="uq_selection_identity"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    selection_id: Mapped[str] = mapped_column(String(120), nullable=False)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    experiment_id: Mapped[str] = mapped_column(String(120), nullable=False)
    experiment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(300), nullable=False)
    missing_context_json: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    reasons_json: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class SelectionMeasurementRow(Base):
    __tablename__ = "selection_measurement"
    __table_args__ = (
        ForeignKeyConstraint(
            ["selection_id"],
            ["objective_experiment_selection.selection_id"],
            name="fk_selection_measurement_selection",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["revision_id", "measurement_key"],
            [
                "measurement_result.paper_experiment_id",
                "measurement_result.measurement_key",
            ],
            name="fk_selection_measurement_measurement",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "selection_id",
            "measurement_key",
            name="uq_selection_measurement_member",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    selection_id: Mapped[str] = mapped_column(String(120), nullable=False)
    revision_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    measurement_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    measurement_key: Mapped[str] = mapped_column(String(100), nullable=False)


class SelectionComparisonRow(Base):
    __tablename__ = "selection_comparison"
    __table_args__ = (
        ForeignKeyConstraint(
            ["selection_id"],
            ["objective_experiment_selection.selection_id"],
            name="fk_selection_comparison_selection",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["revision_id", "comparison_key"],
            [
                "experiment_comparison.paper_experiment_id",
                "experiment_comparison.comparison_key",
            ],
            name="fk_selection_comparison_comparison",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "selection_id",
            "comparison_key",
            name="uq_selection_comparison_member",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    selection_id: Mapped[str] = mapped_column(String(120), nullable=False)
    revision_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    comparison_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    comparison_key: Mapped[str] = mapped_column(String(100), nullable=False)


__all__ = [
    "ObjectiveExperimentSelectionRow",
    "SelectionComparisonRow",
    "SelectionMeasurementRow",
]
