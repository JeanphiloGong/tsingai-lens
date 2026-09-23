"""PostgreSQL row for one Chat correction candidate proposal."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ChatCorrectionCandidateRow(Base):
    __tablename__ = "chat_correction_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('needs_review', 'ambiguous', 'no_candidate', 'invalid_proposal', 'provider_failed')",
            name="chat_correction_candidate_status_valid",
        ),
        CheckConstraint("length(digest) = 64", name="chat_correction_candidate_digest_length"),
        CheckConstraint("updated_at >= created_at", name="chat_correction_candidate_times_valid"),
    )

    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("collections.collection_id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True
    )
    challenge_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    answer_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False, default=list, server_default="[]")
    model_call_ids: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    proposal: Mapped[dict[str, Any] | None] = mapped_column(_JSON_DOCUMENT, nullable=True)
    request: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    selected_case_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("chat_correction_cases.case_id", ondelete="SET NULL"), nullable=True
    )
    selected_sample_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("chat_correction_samples.sample_id", ondelete="SET NULL"), nullable=True
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["ChatCorrectionCandidateRow"]
