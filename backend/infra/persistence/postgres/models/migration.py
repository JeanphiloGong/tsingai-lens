"""Sanitized audit record for the one-way Objective identity import."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ObjectiveIdentityMigration(Base):
    __tablename__ = "objective_identity_migrations"
    __table_args__ = (
        CheckConstraint("length(source_sha256) = 64", name="source_sha256_length"),
        CheckConstraint("length(manifest_sha256) = 64", name="manifest_sha256_length"),
        CheckConstraint("status = 'applied'", name="status_applied"),
    )

    source_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    backup_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    record_counts: Mapped[dict[str, int]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    content_hashes: Mapped[dict[str, str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["ObjectiveIdentityMigration"]
