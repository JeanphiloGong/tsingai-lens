"""Current Objective discovery and versioned analysis aggregate storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ObjectiveDiscoveryRecord(Base):
    """The current discovery result for one selected collection scope."""

    __tablename__ = "objective_discovery"

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    research_objectives_ready: Mapped[bool] = mapped_column(nullable=False)
    document_inputs: Mapped[list[dict[str, str]]] = mapped_column(
        _JSON_DOCUMENT,
        nullable=False,
    )
    objective_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    study_dispositions: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObjectiveResearchRecord(Base):
    """One current ResearchObjective aggregate."""

    __tablename__ = "research_objectives"
    __table_args__ = (
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


class ObjectiveDocumentEvidenceRecord(Base):
    """Private resumable Evidence inspection for one Objective and Document."""

    __tablename__ = "objective_document_evidence_checkpoints"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id"],
            ["research_objectives.collection_id", "research_objectives.objective_id"],
            name="fk_objective_document_evidence_objective",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name="fk_objective_document_evidence_document",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObjectivePaperContributionRecord(Base):
    __tablename__ = "objective_paper_contributions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_objective_contributions_analysis",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ObjectiveEvidenceRecord(Base):
    __tablename__ = "objective_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_objective_evidence_analysis",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            [
                "collection_id",
                "objective_id",
                "analysis_version",
                "source_document_id",
            ],
            [
                "objective_paper_contributions.collection_id",
                "objective_paper_contributions.objective_id",
                "objective_paper_contributions.analysis_version",
                "objective_paper_contributions.source_document_id",
            ],
            name="fk_objective_evidence_contribution",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)


class ObjectiveFindingRecord(Base):
    __tablename__ = "objective_findings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version"],
            [
                "objective_analyses.collection_id",
                "objective_analyses.objective_id",
                "objective_analyses.analysis_version",
            ],
            name="fk_objective_findings_analysis",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)


__all__ = [
    "ObjectiveAnalysisRecord",
    "ObjectiveDocumentEvidenceRecord",
    "ObjectiveDiscoveryRecord",
    "ObjectiveEvidenceRecord",
    "ObjectiveFindingRecord",
    "ObjectivePaperContributionRecord",
    "ObjectiveResearchRecord",
]
