"""Evaluation lineage and Objective review storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class EvaluationGoldSetORM(Base):
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
    items: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class EvaluationPredictionSnapshotORM(Base):
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
    items: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class EvaluationRunORM(Base):
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
    scores: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    failures: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


__all__ = [
    "EvaluationGoldSetORM",
    "EvaluationPredictionSnapshotORM",
    "EvaluationRunORM",
]
