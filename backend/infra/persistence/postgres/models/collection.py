"""Relational storage model for collection metadata."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class StoredObject(Base):
    __tablename__ = "stored_objects"
    __table_args__ = (
        CheckConstraint("object_kind <> ''", name="object_kind_not_empty"),
        CheckConstraint("storage_key <> ''", name="storage_key_not_empty"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        CheckConstraint("sha256 = lower(sha256)", name="sha256_lowercase"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
    )

    object_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("document_versions.document_version_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

class CollectionFile(Base):
    __tablename__ = "collection_files"
    __table_args__ = (
        CheckConstraint("file_order >= 0", name="file_order_non_negative"),
        CheckConstraint("stored_filename <> ''", name="stored_filename_not_empty"),
        CheckConstraint("status <> ''", name="status_not_empty"),
        UniqueConstraint(
            "collection_id",
            "file_id",
            name="uq_collection_files_collection_file_identity",
        ),
        UniqueConstraint(
            "collection_id",
            "file_order",
            name="uq_collection_files_collection_file_order",
        ),
        ForeignKeyConstraint(
            ["collection_id", "collection_document_id"],
            [
                "collection_documents.collection_id",
                "collection_documents.collection_document_id",
            ],
            name="fk_collection_files_collection_document",
            ondelete="RESTRICT",
        ),
    )

    file_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
    )
    object_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("stored_objects.object_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    collection_document_id: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_filename: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
