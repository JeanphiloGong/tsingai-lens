"""ORM records for experiment-backed Findings and their explicit links."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ExperimentFindingRow(Base):
    """A published Finding that points to selections rather than copied facts."""

    __tablename__ = "finding"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_finding_objective_analysis",
            ondelete="CASCADE",
        ),
        UniqueConstraint("finding_id", name="uq_finding_identity"),
        CheckConstraint(
            "analysis_version > 0",
            name="finding_analysis_version_positive",
        ),
        CheckConstraint(
            "certainty >= 0 AND certainty <= 1",
            name="finding_certainty_range",
        ),
        CheckConstraint(
            "display_rank >= 0",
            name="finding_display_rank_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(String(128), nullable=False)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    factors_json: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    outcome: Mapped[str] = mapped_column(String(300), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    assertion_strength: Mapped[str] = mapped_column(String(20), nullable=False)
    attribution_scope: Mapped[str] = mapped_column(String(30), nullable=False)
    synthesis_status: Mapped[str] = mapped_column(String(40), nullable=False)
    certainty: Mapped[float] = mapped_column(Float, nullable=False)
    display_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    mechanisms_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    scientific_context_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    limitations_json: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    source_analysis_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_finding_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    created_by_tool_call_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    warnings_json: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class FindingSelectionRow(Base):
    __tablename__ = "finding_selection"
    __table_args__ = (
        ForeignKeyConstraint(
            ["finding_id"],
            ["finding.finding_id"],
            name="fk_finding_selection_finding",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["selection_id"],
            ["objective_experiment_selection.selection_id"],
            name="fk_finding_selection_selection",
            ondelete="RESTRICT",
        ),
    )

    finding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    selection_id: Mapped[str] = mapped_column(String(120), primary_key=True)


class FindingComparisonGroupRow(Base):
    __tablename__ = "finding_comparison_group"
    __table_args__ = (
        ForeignKeyConstraint(
            ["finding_id"],
            ["finding.finding_id"],
            name="fk_finding_comparison_group_finding",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["group_id"],
            ["comparison_group.group_id"],
            name="fk_finding_comparison_group_group",
            ondelete="RESTRICT",
        ),
    )

    finding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(120), primary_key=True)


__all__ = [
    "ExperimentFindingRow",
    "FindingComparisonGroupRow",
    "FindingSelectionRow",
]
