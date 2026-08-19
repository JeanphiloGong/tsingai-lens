"""Objective-scoped experiment-plan storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


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
    metadata_json: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("auth_users.user_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["ObjectiveExperimentPlan"]
