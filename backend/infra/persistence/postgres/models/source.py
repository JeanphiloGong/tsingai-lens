"""Versioned relational Source document-structure models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
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


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        CheckConstraint(
            "human_readable_id >= 0", name="human_readable_id_non_negative"
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_source_documents_collection_build",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "collection_document_id", "document_version_id"],
            [
                "collection_documents.collection_id",
                "collection_documents.collection_document_id",
                "collection_documents.document_version_id",
            ],
            name="fk_source_documents_membership_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "source_document_id",
            name="uq_source_documents_collection_build_document",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    collection_document_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    human_readable_id: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    creation_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


class SourceTextUnit(Base):
    __tablename__ = "source_text_units"
    __table_args__ = (
        CheckConstraint(
            "human_readable_id >= 0", name="human_readable_id_non_negative"
        ),
        CheckConstraint(
            "n_tokens IS NULL OR n_tokens >= 0", name="n_tokens_non_negative"
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id"],
            ["collection_builds.collection_id", "collection_builds.build_id"],
            name="fk_source_text_units_collection_build",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "text_unit_id",
            name="uq_source_text_units_collection_build_text_unit",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    text_unit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    human_readable_id: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    n_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SourceTextUnitDocument(Base):
    __tablename__ = "source_text_unit_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "build_id", "text_unit_id"],
            [
                "source_text_units.collection_id",
                "source_text_units.build_id",
                "source_text_units.text_unit_id",
            ],
            name="fk_source_text_unit_documents_text_unit",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_text_unit_documents_document",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    text_unit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False)


class SourceBlock(Base):
    __tablename__ = "source_blocks"
    __table_args__ = (
        CheckConstraint("block_order >= 0", name="block_order_non_negative"),
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_blocks_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id", "build_id", "block_id", name="uq_source_blocks_identity"
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    block_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    block_type: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    block_order: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    char_range_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SourceBlockTextUnit(Base):
    __tablename__ = "source_block_text_units"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "build_id", "block_id"],
            [
                "source_blocks.collection_id",
                "source_blocks.build_id",
                "source_blocks.block_id",
            ],
            name="fk_source_block_text_units_block",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "text_unit_id"],
            [
                "source_text_units.collection_id",
                "source_text_units.build_id",
                "source_text_units.text_unit_id",
            ],
            name="fk_source_block_text_units_text_unit",
            ondelete="CASCADE",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    block_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    text_unit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False)


class SourceTable(Base):
    __tablename__ = "source_tables"
    __table_args__ = (
        CheckConstraint("table_order >= 0", name="table_order_non_negative"),
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_tables_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "source_document_id",
            "table_id",
            name="uq_source_tables_document_table",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    table_order: Mapped[int] = mapped_column(Integer, nullable=False)
    caption_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_block_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    column_headers: Mapped[list[str]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    table_matrix: Mapped[list[list[str]]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


class SourceTableRow(Base):
    __tablename__ = "source_table_rows"
    __table_args__ = (
        CheckConstraint("row_index >= 0", name="row_index_non_negative"),
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "table_id"],
            [
                "source_tables.collection_id",
                "source_tables.build_id",
                "source_tables.source_document_id",
                "source_tables.table_id",
            ],
            name="fk_source_table_rows_table",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id", "build_id", "row_id", name="uq_source_table_rows_identity"
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    row_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    table_id: Mapped[str] = mapped_column(String(128), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    row_text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceTableCell(Base):
    __tablename__ = "source_table_cells"
    __table_args__ = (
        CheckConstraint("row_index >= 0", name="row_index_non_negative"),
        CheckConstraint("col_index >= 0", name="col_index_non_negative"),
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "table_id"],
            [
                "source_tables.collection_id",
                "source_tables.build_id",
                "source_tables.source_document_id",
                "source_tables.table_id",
            ],
            name="fk_source_table_cells_table",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "cell_id",
            name="uq_source_table_cells_identity",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cell_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    table_id: Mapped[str] = mapped_column(String(128), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    col_index: Mapped[int] = mapped_column(Integer, nullable=False)
    cell_text: Mapped[str] = mapped_column(Text, nullable=False)
    header_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    char_range_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    unit_hint: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "SourceBlock",
    "SourceBlockTextUnit",
    "SourceDocument",
    "SourceTable",
    "SourceTableCell",
    "SourceTableRow",
    "SourceTextUnit",
    "SourceTextUnitDocument",
]
