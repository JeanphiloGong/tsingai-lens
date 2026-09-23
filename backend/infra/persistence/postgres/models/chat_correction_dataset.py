"""PostgreSQL row for immutable Chat correction dataset manifests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ChatCorrectionDatasetManifestRow(Base):
    __tablename__ = "chat_correction_datasets"
    __table_args__ = (
        CheckConstraint("length(manifest_digest) = 64", name="chat_correction_dataset_digest_length"),
        CheckConstraint("length(provenance_digest) = 64", name="chat_correction_dataset_provenance_digest_length"),
        CheckConstraint("row_count >= 0", name="chat_correction_dataset_row_count_nonnegative"),
        CheckConstraint("excluded_count >= 0", name="chat_correction_dataset_excluded_count_nonnegative"),
        UniqueConstraint("owner_id", "manifest_digest", name="uq_chat_correction_dataset_owner_digest"),
    )

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("auth_users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("collections.collection_id", ondelete="CASCADE"), nullable=False, index=True
    )
    manifest: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provenance_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["ChatCorrectionDatasetManifestRow"]
