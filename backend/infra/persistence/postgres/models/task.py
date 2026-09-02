"""Relational storage for observable execution tasks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial_success', 'failed')",
            name="valid_status",
        ),
        CheckConstraint("current_stage <> ''", name="current_stage_not_empty"),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="valid_progress_percent",
        ),
        CheckConstraint("updated_at >= created_at", name="valid_timestamps"),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="valid_started_at",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name="valid_finished_at",
        ),
        Index(
            "uq_tasks_active_document_type",
            "document_id",
            "task_type",
            unique=True,
            postgresql_where=text(
                "document_id IS NOT NULL AND status IN ('queued', 'running')"
            ),
            sqlite_where=text(
                "document_id IS NOT NULL AND status IN ('queued', 'running')"
            ),
        ),
    )

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(128), nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    progress_detail: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT,
        nullable=True,
    )
    errors: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TaskStage(Base):
    __tablename__ = "task_stages"
    __table_args__ = (
        CheckConstraint("stage_kind <> ''", name="stage_kind_not_empty"),
        CheckConstraint("stage_order >= 0", name="stage_order_non_negative"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')",
            name="valid_status",
        ),
        UniqueConstraint("task_id", "stage_kind", name="uq_task_stages_task_kind"),
        UniqueConstraint("task_id", "stage_order", name="uq_task_stages_task_order"),
    )

    stage_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    stage_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    errors: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    dependencies: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    output_summary: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)


__all__ = ["Task", "TaskStage"]
