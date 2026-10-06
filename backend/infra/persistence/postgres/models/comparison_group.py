"""ORM records for optional cross-paper ComparisonGroups."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKeyConstraint,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ComparisonGroupRow(Base):
    __tablename__ = "comparison_group"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_comparison_group_objective_analysis",
            ondelete="CASCADE",
        ),
        UniqueConstraint("group_id", name="uq_comparison_group_identity"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(120), nullable=False)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(300), nullable=False)
    comparison_target: Mapped[str] = mapped_column(String(40), nullable=False)
    comparison_basis_json: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    normalizations_json: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    limitations_json: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ComparisonGroupMemberRow(Base):
    __tablename__ = "comparison_group_member"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id"],
            ["comparison_group.group_id"],
            name="fk_comparison_group_member_group",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["selection_id"],
            ["objective_experiment_selection.selection_id"],
            name="fk_comparison_group_member_selection",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "group_id",
            "selection_id",
            name="uq_comparison_group_member_identity",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(120), nullable=False)
    selection_id: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    comparability: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


__all__ = ["ComparisonGroupMemberRow", "ComparisonGroupRow"]
