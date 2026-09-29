"""PostgreSQL records for maintained feedback datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
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


__all__ = ["FeedbackDatasetRow"]
