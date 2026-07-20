"""Objective-scoped expert feedback and curation storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKeyConstraint, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ResearchUnderstandingFeedbackRecord(Base):
    __tablename__ = "research_understanding_feedback_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["understanding_id", "claim_id"],
            ["research_claims.understanding_id", "research_claims.claim_id"],
            name="fk_understanding_feedback_claim",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["understanding_id", "finding_id"],
            ["research_findings.understanding_id", "research_findings.finding_id"],
            name="fk_understanding_feedback_finding",
            ondelete="CASCADE",
        ),
    )

    feedback_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    understanding_id: Mapped[str] = mapped_column(String(128), nullable=False)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    finding_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_id: Mapped[str] = mapped_column(String(128), nullable=False)
    finding_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_status: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchUnderstandingCurationRecord(Base):
    __tablename__ = "research_understanding_curation_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["understanding_id", "claim_id"],
            ["research_claims.understanding_id", "research_claims.claim_id"],
            name="fk_understanding_curations_claim",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["understanding_id", "finding_id"],
            ["research_findings.understanding_id", "research_findings.finding_id"],
            name="fk_understanding_curations_finding",
            ondelete="CASCADE",
        ),
    )

    curation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    understanding_id: Mapped[str] = mapped_column(String(128), nullable=False)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    objective_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    finding_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_id: Mapped[str] = mapped_column(String(128), nullable=False)
    finding_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    curated_claim_type: Mapped[str] = mapped_column(String(64), nullable=False)
    curated_status: Mapped[str] = mapped_column(String(64), nullable=False)
    curated_statement: Mapped[str] = mapped_column(Text, nullable=False)
    curated_support_grade: Mapped[str | None] = mapped_column(String(64), nullable=True)
    curated_review_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    curated_variables: Mapped[list[Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    curated_mediators: Mapped[list[Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    curated_outcomes: Mapped[list[Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    curated_direction: Mapped[str | None] = mapped_column(String(64), nullable=True)
    curated_scope_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    curated_evidence_ref_ids: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    curated_context_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "ResearchUnderstandingCurationRecord",
    "ResearchUnderstandingFeedbackRecord",
]
