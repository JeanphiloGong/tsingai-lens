"""Research objectives, analysis selections, comparison groups and follow-up plans."""

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
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
_AUTOINCREMENT_ID = BigInteger().with_variant(Integer(), "sqlite")


class ObjectiveResearchORM(Base):
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


class ObjectiveAnalysisORM(Base):
    __tablename__ = "objective_analyses"
    __table_args__ = (
        Index("ix_objective_analyses_worker_claim", "status", "lease_expires_at", "created_at"),
        ForeignKeyConstraint(
            ["collection_id", "objective_id"],
            ["research_objectives.collection_id", "research_objectives.objective_id"],
            name="fk_objective_analyses_objective",
            ondelete="CASCADE",
        ),
    )

    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObjectiveAnalysisLegacyCheckpointORM(Base):
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


class ObjectiveExperimentSelectionORM(Base):
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


class SelectionMeasurementORM(Base):
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


class SelectionComparisonORM(Base):
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


class ComparisonGroupORM(Base):
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


class ComparisonGroupMemberORM(Base):
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


class ObjectiveExperimentPlanORM(Base):
    __tablename__ = "objective_experiment_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "objective_id"],
            [
                "research_objectives.collection_id",
                "research_objectives.objective_id",
            ],
            name="fk_objective_experiment_plans_objective",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "parent_plan_id",
            name="uq_objective_experiment_plans_parent_plan_id",
        ),
    )

    plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey(
            "chat_messages.message_id",
            name="fk_objective_experiment_plans_source_message_id_chat_messages",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    source_links: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    plan_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    parent_plan_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey(
            "objective_experiment_plans.plan_id",
            name="fk_objective_experiment_plans_parent_plan_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    structured_plan: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT,
        nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


__all__ = [
    "ObjectiveAnalysisORM",
    "ObjectiveAnalysisLegacyCheckpointORM",
    "ObjectiveResearchORM",
    "ObjectiveExperimentSelectionORM",
    "SelectionComparisonORM",
    "SelectionMeasurementORM",
    "ComparisonGroupMemberORM",
    "ComparisonGroupORM",
    "ObjectiveExperimentPlanORM",
]
