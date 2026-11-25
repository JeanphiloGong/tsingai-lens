"""Workspaces, their current documents and document preparations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    JSON,
    String,
    Text,
    BigInteger,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class WorkspaceORM(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("updated_at >= created_at", name="valid_timestamps"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    discovery_ready: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
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
class DocumentORM(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        CheckConstraint("sha256 = lower(sha256)", name="sha256_lowercase"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint("document_order >= 0", name="document_order_non_negative"),
        UniqueConstraint("workspace_id", "sha256", name="uq_documents_workspace_content"),
        UniqueConstraint(
            "workspace_id", "document_order", name="uq_documents_workspace_order"
        ),
    )

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workspaces.workspace_id", ondelete="CASCADE"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentPreparationORM(Base):
    """One current preparation result, with named Source/Profile sections.

    The file identity remains on ``documents``.  This row owns generated
    artifacts and their provenance so a parser or profile retry replaces one
    document-scoped aggregate instead of synchronizing two current tables.
    """

    __tablename__ = "document_preparations"

    document_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    source_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parser_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    paper_map_payload: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "WorkspaceORM",
    "DocumentORM",
    "DocumentPreparationORM",
]
