"""Current documents owned directly by one collection."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        CheckConstraint("sha256 = lower(sha256)", name="sha256_lowercase"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint("document_order >= 0", name="document_order_non_negative"),
        UniqueConstraint("collection_id", "sha256", name="uq_documents_collection_content"),
        UniqueConstraint(
            "collection_id", "document_order", name="uq_documents_collection_order"
        ),
    )

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_order: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    document_analysis_version: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    preparation_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["Document"]
