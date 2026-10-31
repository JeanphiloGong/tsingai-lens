"""SQLAlchemy mappings for expert Finding reviews."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class FindingFeedbackORM(Base):
    __tablename__ = "finding_feedback_records"
    __table_args__ = (
        # Finding identity is validated against the JSON result payload by
        # the review repository; Findings are no longer separate SQL rows.
    )

    feedback_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    finding_id: Mapped[str] = mapped_column(String(128), nullable=False)
    review_status: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class FindingCurationORM(Base):
    __tablename__ = "finding_curation_records"
    __table_args__ = (
        # Finding identity is validated against the JSON result payload by
        # the review repository; Findings are no longer separate SQL rows.
    )

    curation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    finding_id: Mapped[str] = mapped_column(String(128), nullable=False)
    curated_status: Mapped[str] = mapped_column(String(64), nullable=False)
    curated_finding: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


__all__ = ['FindingFeedbackORM', 'FindingCurationORM']
