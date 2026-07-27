"""Evaluation lineage and Objective review storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class EvaluationGoldSetRecord(Base):
    __tablename__ = "evaluation_gold_sets"

    gold_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    target_layer: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_profile: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class EvaluationGoldItemRecord(Base):
    __tablename__ = "evaluation_gold_items"
    __table_args__ = (
        Index(
            "ix_evaluation_gold_items_gold_family", "gold_id", "family", "document_id"
        ),
    )

    gold_item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    gold_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("evaluation_gold_sets.gold_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(Text, nullable=False)
    family: Mapped[str] = mapped_column(String(128), nullable=False)
    item_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


class EvaluationPredictionSnapshotRecord(Base):
    __tablename__ = "evaluation_prediction_snapshots"
    __table_args__ = (
        Index("ix_evaluation_snapshots_collection", "collection_id", "fact_source"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_layer: Mapped[str] = mapped_column(String(32), nullable=False)
    fact_source: Mapped[str] = mapped_column(String(64), nullable=False)
    system_context: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    artifact_counts: Mapped[dict[str, int]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class EvaluationPredictionItemRecord(Base):
    __tablename__ = "evaluation_prediction_items"
    __table_args__ = (
        Index(
            "ix_evaluation_prediction_items_family",
            "snapshot_id",
            "family",
            "document_id",
        ),
    )

    snapshot_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("evaluation_prediction_snapshots.snapshot_id", ondelete="CASCADE"),
        primary_key=True,
    )
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(Text, nullable=False)
    family: Mapped[str] = mapped_column(String(128), nullable=False)
    item_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class EvaluationRunRecord(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("ix_evaluation_runs_collection", "collection_id", "created_at"),
    )

    evaluation_run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
    )
    gold_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("evaluation_gold_sets.gold_id", ondelete="RESTRICT"),
        nullable=False,
    )
    prediction_snapshot_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("evaluation_prediction_snapshots.snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_layer: Mapped[str] = mapped_column(String(32), nullable=False)
    fact_source: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_profile: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class EvaluationScoreRecord(Base):
    __tablename__ = "evaluation_scores"

    score_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    evaluation_run_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("evaluation_runs.evaluation_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    family: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    numerator: Mapped[float | None] = mapped_column(Float, nullable=True)
    denominator: Mapped[float | None] = mapped_column(Float, nullable=True)


class EvaluationFailureRecord(Base):
    __tablename__ = "evaluation_failures"
    __table_args__ = (
        Index(
            "ix_evaluation_failures_family",
            "evaluation_run_id",
            "family",
            "failure_type",
        ),
    )

    failure_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    evaluation_run_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("evaluation_runs.evaluation_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(Text, nullable=False)
    family: Mapped[str] = mapped_column(String(128), nullable=False)
    failure_type: Mapped[str] = mapped_column(String(64), nullable=False)
    likely_layer: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    gold_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prediction_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gold: Mapped[dict[str, Any] | None] = mapped_column(_JSON_DOCUMENT, nullable=True)
    prediction: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


class FindingFeedbackRecord(Base):
    __tablename__ = "finding_feedback_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version", "finding_id"],
            [
                "objective_findings.collection_id",
                "objective_findings.objective_id",
                "objective_findings.analysis_version",
                "objective_findings.finding_id",
            ],
            name="fk_finding_feedback_finding",
            ondelete="CASCADE",
        ),
    )

    feedback_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    finding_id: Mapped[str] = mapped_column(String(128), nullable=False)
    review_status: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class FindingCurationRecord(Base):
    __tablename__ = "finding_curation_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id", "analysis_version", "finding_id"],
            [
                "objective_findings.collection_id",
                "objective_findings.objective_id",
                "objective_findings.analysis_version",
                "objective_findings.finding_id",
            ],
            name="fk_finding_curations_finding",
            ondelete="CASCADE",
        ),
    )

    curation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    finding_id: Mapped[str] = mapped_column(String(128), nullable=False)
    curated_status: Mapped[str] = mapped_column(String(64), nullable=False)
    curated_statement: Mapped[str] = mapped_column(Text, nullable=False)
    curated_support_grade: Mapped[str | None] = mapped_column(String(64), nullable=True)
    curated_review_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    curated_variables: Mapped[list[Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    curated_mediators: Mapped[list[Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    curated_outcomes: Mapped[list[Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    curated_direction: Mapped[str | None] = mapped_column(String(64), nullable=True)
    curated_scope_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    curated_evidence_ids: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


__all__ = [
    "EvaluationFailureRecord",
    "EvaluationGoldItemRecord",
    "EvaluationGoldSetRecord",
    "EvaluationPredictionItemRecord",
    "EvaluationPredictionSnapshotRecord",
    "EvaluationRunRecord",
    "EvaluationScoreRecord",
    "FindingCurationRecord",
    "FindingFeedbackRecord",
]
