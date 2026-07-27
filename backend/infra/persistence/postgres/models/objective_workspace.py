"""Objective-scoped session, message, and experiment-plan storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class ObjectiveSession(Base):
    __tablename__ = "objective_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "focused_objective_id"],
            [
                "research_objectives.collection_id",
                "research_objectives.objective_id",
            ],
            name="fk_objective_sessions_focus",
            ondelete="SET NULL",
        ),
    )

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.user_id", ondelete="CASCADE"), nullable=False
    )
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("collections.collection_id", ondelete="CASCADE"), nullable=False
    )
    focused_material_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    focused_paper_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    focused_objective_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    goal_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_brief: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    answer_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    rolling_summary: Mapped[str] = mapped_column(Text, nullable=False)
    last_evidence_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    last_material_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    last_paper_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    collection_data_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObjectiveMessage(Base):
    __tablename__ = "objective_messages"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position_non_negative"),
        UniqueConstraint("session_id", "position", name="uq_objective_messages_position"),
    )

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("objective_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    used_evidence_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    links: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    source_links: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    review_gate: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_finding_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObjectiveExperimentPlan(Base):
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
    )

    plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("objective_messages.message_id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_links: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("auth_users.user_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["ObjectiveExperimentPlan", "ObjectiveMessage", "ObjectiveSession"]
