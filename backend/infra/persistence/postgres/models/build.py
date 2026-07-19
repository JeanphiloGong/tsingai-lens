"""Relational storage model for task and collection-build lineage."""

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
    )

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(128), nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    progress_detail: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT,
        nullable=True,
    )
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    errors: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CollectionBuild(Base):
    __tablename__ = "collection_builds"
    __table_args__ = (
        CheckConstraint("build_number > 0", name="build_number_positive"),
        CheckConstraint(
            "status IN ('queued', 'building', 'succeeded', 'failed', 'cancelled')",
            name="valid_status",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="valid_started_at",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name="valid_finished_at",
        ),
        UniqueConstraint(
            "collection_id",
            "build_number",
            name="uq_collection_builds_collection_build_number",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            name="uq_collection_builds_collection_build_identity",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    build_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BuildStage(Base):
    __tablename__ = "build_stages"
    __table_args__ = (
        CheckConstraint("stage_kind <> ''", name="stage_kind_not_empty"),
        CheckConstraint("stage_version > 0", name="stage_version_positive"),
        CheckConstraint("stage_order >= 0", name="stage_order_non_negative"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')",
            name="valid_status",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="valid_timestamps",
        ),
        UniqueConstraint(
            "build_id",
            "stage_kind",
            "stage_version",
            name="uq_build_stages_build_kind_version",
        ),
        UniqueConstraint(
            "build_id",
            "stage_order",
            name="uq_build_stages_build_stage_order",
        ),
    )

    stage_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    build_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collection_builds.build_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    stage_version: Mapped[int] = mapped_column(Integer, nullable=False)
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
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        CheckConstraint("artifact_kind <> ''", name="artifact_kind_not_empty"),
        CheckConstraint("schema_version > 0", name="schema_version_positive"),
        CheckConstraint("content_version > 0", name="content_version_positive"),
        CheckConstraint(
            "status IN ('generated', 'ready', 'stale')",
            name="valid_status",
        ),
        UniqueConstraint(
            "build_stage_id",
            "artifact_kind",
            "schema_version",
            "content_version",
            name="uq_artifact_versions_stage_kind_version",
        ),
    )

    artifact_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    build_stage_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("build_stages.stage_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("stored_objects.object_id", ondelete="RESTRICT"),
        nullable=True,
    )
    details: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class CollectionActiveBuild(Base):
    __tablename__ = "collection_active_builds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_active_builds_collection_build",
            ondelete="CASCADE",
        ),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    build_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


__all__ = [
    "ArtifactVersion",
    "BuildStage",
    "CollectionActiveBuild",
    "CollectionBuild",
    "Task",
]
