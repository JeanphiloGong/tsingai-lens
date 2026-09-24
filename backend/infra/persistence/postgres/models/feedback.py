"""Persistence records for model-call audit and feedback analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class ChatModelCallRow(Base):
    """One exact request submitted to an LLM provider."""

    __tablename__ = "chat_model_calls"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('decision', 'compaction', 'finalization')",
            name="chat_model_call_purpose_valid",
        ),
        CheckConstraint(
            "status IN ('recorded', 'provider_succeeded', 'provider_failed', "
            "'response_invalid', 'cancelled')",
            name="chat_model_call_status_valid",
        ),
        CheckConstraint("length(request_digest) = 64", name="chat_model_call_digest_length"),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="chat_model_call_timestamps_valid",
        ),
    )

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger_message_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    response_message_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AnalysisJobRow(Base):
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


class FeedbackAnalysisResultRow(Base):
    """AI candidate analysis and its user-readable evidence coverage."""

    __tablename__ = "feedback_analysis_results"
    __table_args__ = (
        CheckConstraint(
            "problem_type IN ('fact_error', 'source_missing', 'evidence_mismatch', "
            "'retrieval_failure', 'tool_failure', 'intent_mismatch', "
            "'incomplete_answer', 'style_or_format', 'undetermined_dissatisfaction')",
            name="feedback_analysis_problem_type_valid",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="feedback_analysis_confidence_range",
        ),
        CheckConstraint("length(input_digest) = 64", name="feedback_analysis_input_digest_length"),
        UniqueConstraint("job_id", name="uq_feedback_analysis_results_job_id"),
    )

    result_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("analysis_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feedback_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    anchor_message_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    problem_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(nullable=False)
    related_message_ids: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list
    )
    suggested_evidence: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list
    )
    suggested_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_coverage: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FeedbackCaseRow(Base):
    """Human-facing case assembled from one or more analysis signals."""

    __tablename__ = "feedback_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('detected', 'collecting_context', 'needs_annotation', "
            "'ready_for_review', 'rejected', 'insufficient', 'accepted', 'withdrawn')",
            name="feedback_case_status_valid",
        ),
        CheckConstraint(
            "updated_at >= created_at", name="feedback_case_timestamps_valid"
        ),
        UniqueConstraint(
            "session_id", "anchor_message_id", name="uq_feedback_cases_session_anchor"
        ),
        Index(
            "ix_feedback_cases_collection_status",
            "collection_id",
            "status",
            "created_at",
        ),
    )

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    anchor_message_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_signal_ids: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list
    )
    analysis_result_ids: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list
    )
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    annotation_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)


__all__ = [
    "AnalysisJobRow",
    "ChatModelCallRow",
    "FeedbackAnalysisResultRow",
    "FeedbackCaseRow",
]
