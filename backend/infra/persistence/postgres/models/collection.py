"""Relational storage model for collection metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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


class CollectionImport(Base):
    __tablename__ = "collection_imports"
    __table_args__ = (
        CheckConstraint("channel <> ''", name="channel_not_empty"),
        CheckConstraint("adapter_name <> ''", name="adapter_name_not_empty"),
        CheckConstraint("import_order >= 0", name="import_order_non_negative"),
        UniqueConstraint(
            "collection_id",
            "import_id",
            name="uq_collection_imports_collection_import_identity",
        ),
        UniqueConstraint(
            "collection_id",
            "import_order",
            name="uq_collection_imports_collection_import_order",
        ),
    )

    import_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_name: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_locator: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal_context: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT,
        nullable=True,
    )
    warnings: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    import_order: Mapped[int] = mapped_column(Integer, nullable=False)


class CollectionImportDocument(Base):
    __tablename__ = "collection_import_documents"
    __table_args__ = (
        CheckConstraint("document_order >= 0", name="document_order_non_negative"),
        CheckConstraint("origin_channel <> ''", name="origin_channel_not_empty"),
        CheckConstraint("ingest_status <> ''", name="ingest_status_not_empty"),
        ForeignKeyConstraint(
            ["collection_id", "file_id"],
            ["collection_files.collection_id", "collection_files.file_id"],
            name="fk_import_documents_collection_file",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "import_id"],
            ["collection_imports.collection_id", "collection_imports.import_id"],
            name="fk_import_documents_collection_import",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "import_id",
            "source_document_id",
            name="uq_import_documents_import_source_document",
        ),
        UniqueConstraint(
            "import_id",
            "document_order",
            name="uq_import_documents_import_document_order",
        ),
    )

    file_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    import_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(255), nullable=False)
    origin_channel: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingest_status: Mapped[str] = mapped_column(String(64), nullable=False)
    text_units: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSON_DOCUMENT,
        nullable=False,
    )
    document_order: Mapped[int] = mapped_column(Integer, nullable=False)


class CollectionHandoff(Base):
    __tablename__ = "collection_handoffs"
    __table_args__ = (
        CheckConstraint("handoff_order >= 0", name="handoff_order_non_negative"),
        CheckConstraint("kind <> ''", name="kind_not_empty"),
        CheckConstraint("status <> ''", name="status_not_empty"),
        UniqueConstraint(
            "collection_id",
            "handoff_order",
            name="uq_collection_handoffs_collection_handoff_order",
        ),
    )

    handoff_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_channels: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    goal_context: Mapped[dict[str, Any]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    handoff_order: Mapped[int] = mapped_column(Integer, nullable=False)
