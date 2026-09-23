"""PostgreSQL rows for immutable Chat correction samples and review logs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ChatCorrectionSampleRow(Base):
    __tablename__ = "chat_correction_samples"
    __table_args__ = (
        CheckConstraint("length(digest) = 64", name="chat_correction_sample_digest_length"),
        CheckConstraint("length(target) > 0", name="chat_correction_sample_target_nonempty"),
        UniqueConstraint("case_id", name="uq_chat_correction_sample_case"),
    )

    sample_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chat_correction_cases.case_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    model_call_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chat_model_calls.call_id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    input: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    observations: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    target: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatCorrectionReviewRow(Base):
    __tablename__ = "chat_correction_reviews"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('accept', 'reject', 'insufficient', 'withdraw')",
            name="chat_correction_review_decision_valid",
        ),
        CheckConstraint("seq >= 1", name="chat_correction_review_seq_positive"),
        CheckConstraint("length(sample_digest) = 64", name="chat_correction_review_digest_length"),
        UniqueConstraint("sample_id", "seq", name="uq_chat_correction_review_sample_seq"),
    )

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sample_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chat_correction_samples.sample_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sample_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.user_id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_message_ids: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["ChatCorrectionReviewRow", "ChatCorrectionSampleRow"]
