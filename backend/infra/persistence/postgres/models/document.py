"""Canonical document identity and collection membership models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


class Document(Base):
    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        CheckConstraint("sha256 = lower(sha256)", name="sha256_lowercase"),
        UniqueConstraint(
            "document_id",
            "document_version_id",
            name="uq_document_versions_document_version_identity",
        ),
    )

    document_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    media_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class CollectionDocument(Base):
    __tablename__ = "collection_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "document_version_id"],
            ["document_versions.document_id", "document_versions.document_version_id"],
            name="fk_collection_documents_document_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "collection_id",
            "document_id",
            name="uq_collection_documents_collection_document",
        ),
        UniqueConstraint(
            "collection_id",
            "collection_document_id",
            name="uq_collection_documents_collection_membership_identity",
        ),
        UniqueConstraint(
            "collection_id",
            "collection_document_id",
            "document_version_id",
            name="uq_collection_documents_membership_version",
        ),
    )

    collection_document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
