"""Canonical parsed Source artifact for one current document."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class DocumentSource(Base):
    """Persist one complete, format-neutral Source artifact as a tree envelope."""

    __tablename__ = "document_sources"
    document_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    source_format: Mapped[str] = mapped_column(String(32), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["DocumentSource"]
