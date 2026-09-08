"""Relational storage for collection metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (
        CheckConstraint("paper_count >= 0", name="paper_count_non_negative"),
        CheckConstraint("updated_at >= created_at", name="valid_timestamps"),
    )

    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("auth_users.user_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    paper_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discovery_ready: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    discovery_document_inputs: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    discovery_objective_ids: Mapped[list[str]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    discovery_study_dispositions: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False, default=list, server_default="[]"
    )
    discovery_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["Collection"]
