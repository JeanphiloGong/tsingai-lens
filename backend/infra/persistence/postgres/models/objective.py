"""Current Objective discovery and versioned analysis aggregate storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    JSON,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
_AUTOINCREMENT_ID = BigInteger().with_variant(Integer(), "sqlite")


class ObjectiveResearchRecord(Base):
    """One current ResearchObjective aggregate."""

    __tablename__ = "research_objectives"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name="fk_research_objectives_collection",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "created_by_tool_call_id",
            name="uq_research_objectives_created_by_tool_call",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_tool_call_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObjectiveAnalysisRecord(Base):
    __tablename__ = "objective_analyses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id"],
            ["research_objectives.collection_id", "research_objectives.objective_id"],
            name="fk_objective_analyses_objective",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObjectiveAnalysisLegacyCheckpointRecord(Base):
    """Audit-only classification of retired per-document checkpoints."""

    __tablename__ = "objective_analysis_legacy_checkpoints"
    __table_args__ = (
        Index(
            "ix_objective_analysis_legacy_checkpoints_objective",
            "collection_id",
            "objective_id",
            "analysis_version",
        ),
        UniqueConstraint(
            "collection_id",
            "objective_id",
            "analysis_version",
            "legacy_key",
            name="uq_objective_analysis_legacy_checkpoint_key",
        ),
    )

    id: Mapped[int] = mapped_column(
        _AUTOINCREMENT_ID,
        primary_key=True,
        autoincrement=True,
    )
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    legacy_key: Mapped[str] = mapped_column(String(400), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checkpoint_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "ObjectiveAnalysisRecord",
    "ObjectiveAnalysisLegacyCheckpointRecord",
    "ObjectiveResearchRecord",
]
