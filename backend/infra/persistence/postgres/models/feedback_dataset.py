"""PostgreSQL records for maintained feedback datasets."""

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
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class FeedbackDatasetRow(Base):
    __tablename__ = "feedback_datasets"
    __table_args__ = (
        CheckConstraint(
            "task_type IN ('sft', 'preference', 'evaluation')",
            name="feedback_dataset_task_type_valid",
        ),
        CheckConstraint("spec_version >= 1", name="feedback_dataset_spec_version_positive"),
        Index(
            "ix_feedback_datasets_collection_created",
            "collection_id",
            "created_at",
        ),
    )

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    task_type: Mapped[str] = mapped_column(String(16), nullable=False)
    construction_spec: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    spec_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("auth_users.user_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FeedbackDatasetSampleRow(Base):
    """Mutable sample identity pointing at immutable content revisions."""

    __tablename__ = "feedback_dataset_samples"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'building', 'needs_confirmation', 'needs_input', "
            "'confirmed', 'discarded', 'build_failed')",
            name="feedback_dataset_sample_status_valid",
        ),
        CheckConstraint("generation >= 1", name="feedback_dataset_sample_generation_positive"),
        CheckConstraint(
            "length(source_digest) = 64",
            name="feedback_dataset_sample_source_digest_length",
        ),
        UniqueConstraint(
            "dataset_id",
            "source_case_id",
            name="uq_feedback_dataset_samples_dataset_source_case",
        ),
        Index(
            "ix_feedback_dataset_samples_dataset_status",
            "dataset_id",
            "status",
            "updated_at",
        ),
    )

    sample_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("feedback_datasets.dataset_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_case_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("feedback_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    current_revision_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(
            "feedback_sample_revisions.revision_id",
            name="fk_feedback_dataset_samples_current_revision",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    confirmed_revision_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(
            "feedback_sample_revisions.revision_id",
            name="fk_feedback_dataset_samples_confirmed_revision",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    active_job_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("analysis_jobs.job_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    missing_reasons: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT,
        nullable=False,
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("auth_users.user_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FeedbackSampleRevisionRow(Base):
    """Append-only task content and provenance for one sample."""

    __tablename__ = "feedback_sample_revisions"
    __table_args__ = (
        CheckConstraint(
            "author_kind IN ('worker', 'human')",
            name="feedback_sample_revision_author_kind_valid",
        ),
        CheckConstraint("revision_no >= 1", name="feedback_sample_revision_number_positive"),
        CheckConstraint(
            "construction_spec_version >= 1",
            name="feedback_sample_revision_spec_version_positive",
        ),
        CheckConstraint(
            "length(content_digest) = 64",
            name="feedback_sample_revision_content_digest_length",
        ),
        CheckConstraint(
            "length(input_digest) = 64",
            name="feedback_sample_revision_input_digest_length",
        ),
        UniqueConstraint(
            "sample_id",
            "revision_no",
            name="uq_feedback_sample_revisions_sample_number",
        ),
        Index(
            "ix_feedback_sample_revisions_sample_created",
            "sample_id",
            "created_at",
        ),
    )

    revision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sample_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("feedback_dataset_samples.sample_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    author_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    construction_spec_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("auth_users.user_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("analysis_jobs.job_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FeedbackSampleActionRow(Base):
    """One user operation and its idempotent result at submission time."""

    __tablename__ = "feedback_sample_actions"
    __table_args__ = (
        UniqueConstraint("sample_id", "idempotency_key", name="uq_feedback_sample_actions_key"),
        CheckConstraint("generation >= 1", name="feedback_sample_action_generation_positive"),
        CheckConstraint("length(request_digest) = 64", name="feedback_sample_action_digest_length"),
        CheckConstraint(
            "action IN ('rebuild', 'retry', 'discard', 'restore')",
            name="feedback_sample_action_type_valid",
        ),
        Index("ix_feedback_sample_actions_sample_created", "sample_id", "created_at"),
    )

    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sample_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("feedback_dataset_samples.sample_id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.user_id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_revision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_status: Mapped[str] = mapped_column(String(32), nullable=False)
    next_status: Mapped[str] = mapped_column(String(32), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("analysis_jobs.job_id", ondelete="SET NULL"), nullable=True
    )
    result_sample: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "FeedbackDatasetRow",
    "FeedbackDatasetSampleRow",
    "FeedbackSampleRevisionRow",
    "FeedbackSampleActionRow",
]
