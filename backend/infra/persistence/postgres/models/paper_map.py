"""Current bounded Paper Map owned by one collection document."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class PaperMapRow(Base):
    __tablename__ = "paper_maps"

    document_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    map_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)


__all__ = ["PaperMapRow"]
