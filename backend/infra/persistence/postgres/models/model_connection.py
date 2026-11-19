from __future__ import annotations
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Identity, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from infra.persistence.postgres.base import Base


class ModelConnectionORM(Base):
    __tablename__ = "model_connections"

    connection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="chat")
    api_key_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default='false')
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    context_window_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_timeout_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_model_connections_enabled", "enabled"),
        CheckConstraint("kind IN ('chat', 'embedding')", name="kind"),
        CheckConstraint('length(connection_id) BETWEEN 1 AND 64', name='id_length'),
        CheckConstraint('length(btrim(display_name)) BETWEEN 1 AND 100', name='name_length'),
        CheckConstraint('length(base_url) BETWEEN 1 AND 2048', name='base_length'),
        CheckConstraint('length(btrim(model)) BETWEEN 1 AND 200', name='model_length'),
        CheckConstraint('version > 0', name='version_positive'),
        CheckConstraint('context_window_tokens IS NULL OR context_window_tokens > 0', name='context_positive'),
        CheckConstraint('max_output_tokens IS NULL OR max_output_tokens > 0', name='output_positive'),
        CheckConstraint("request_timeout_seconds IS NULL OR (request_timeout_seconds > 0 AND request_timeout_seconds < 'Infinity'::float8)", name='timeout_finite'),
        CheckConstraint('api_key_ciphertext IS NULL OR (octet_length(api_key_ciphertext) BETWEEN 30 AND 8221 AND get_byte(api_key_ciphertext, 0) = 1)', name='ciphertext_format'),

    )


class ModelConnectionAuditORM(Base):
    __tablename__ = "model_connection_audit"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(64), ForeignKey("model_connections.connection_id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(Text)
    actor_display_name: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(BigInteger)
    changes: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("length(actor_id) BETWEEN 1 AND 64", name="actor_length"),
        CheckConstraint("action IN ('create', 'update')", name="action"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("jsonb_typeof(changes) = 'object'", name="changes_object"),
        UniqueConstraint("connection_id", "version"),
    )


class ModelAssignmentORM(Base):
    __tablename__ = "model_assignments"
    __table_args__ = (CheckConstraint("version > 0", name="version_positive"),)

    purpose: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_connections.connection_id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(BigInteger)
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
