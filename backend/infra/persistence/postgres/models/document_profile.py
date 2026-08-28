"""Current document-level profile owned by one collection document."""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class DocumentProfileRow(Base):
    __tablename__ = "document_profiles"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    document_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    parsing_warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


__all__ = ["DocumentProfileRow"]
