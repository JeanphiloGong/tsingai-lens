"""Worker scheduling envelopes and observable pipeline executions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    ForeignKey,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class AnalysisJobORM(Base):
    """Versioned scheduling envelope shared by analysis workers."""

    __tablename__ = "analysis_jobs"
    __table_args__ = (
        CheckConstraint("payload_version >= 1", name="analysis_job_payload_version_positive"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="analysis_job_status_valid",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="analysis_job_timestamps_valid",
        ),
        UniqueConstraint("idempotency_key", name="uq_analysis_jobs_idempotency_key"),
        Index(
            "ix_analysis_jobs_claim",
            "status",
            "available_at",
            "created_at",
        ),
    )

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class PipelineRunORM(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        Index("ix_pipeline_runs_worker_claim", "pipeline_name", "status", "lease_expires_at", "created_at"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial_success', 'failed')",
            name="valid_status",
        ),
        CheckConstraint("pipeline_name <> ''", name="pipeline_name_not_empty"),
        CheckConstraint("scope_type <> ''", name="scope_type_not_empty"),
        CheckConstraint("scope_id <> ''", name="scope_id_not_empty"),
        CheckConstraint("updated_at >= created_at", name="valid_timestamps"),
        Index(
            "uq_pipeline_runs_active_scope",
            "pipeline_name",
            "scope_type",
            "scope_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workspaces.workspace_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pipeline_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    record_json: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "AnalysisJobORM",
    "PipelineRunORM",
]
