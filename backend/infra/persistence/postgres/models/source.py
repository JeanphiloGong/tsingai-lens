"""Versioned relational Source document-structure models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
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
        UniqueConstraint(
            "collection_id",
            "build_id",
            "source_document_id",
            "block_id",
            name="uq_source_blocks_document_block",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    block_id: Mapped[str] = mapped_column(String(), primary_key=True)
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
    block_id: Mapped[str] = mapped_column(String(), primary_key=True)
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
    table_id: Mapped[str] = mapped_column(String(), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    table_order: Mapped[int] = mapped_column(Integer, nullable=False)
    caption_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_block_id: Mapped[str | None] = mapped_column(String(), nullable=True)
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
    row_id: Mapped[str] = mapped_column(String(), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    table_id: Mapped[str] = mapped_column(String(), nullable=False)
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
    table_id: Mapped[str] = mapped_column(String(), nullable=False)
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


class SourceFigure(Base):
    __tablename__ = "source_figures"
    __table_args__ = (
        CheckConstraint("figure_order >= 0", name="figure_order_non_negative"),
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
        CheckConstraint(
            "image_width IS NULL OR image_width >= 0", name="image_width_non_negative"
        ),
        CheckConstraint(
            "image_height IS NULL OR image_height >= 0",
            name="image_height_non_negative",
        ),
        CheckConstraint(
            "image_size_bytes IS NULL OR image_size_bytes >= 0",
            name="image_size_bytes_non_negative",
        ),
        CheckConstraint(
            "(image_storage_key IS NULL AND asset_sha256 IS NULL "
            "AND image_size_bytes IS NULL) OR "
            "(image_storage_key IS NOT NULL AND asset_sha256 IS NOT NULL "
            "AND image_size_bytes IS NOT NULL)",
            name="image_object_complete",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_figures_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "source_document_id",
            "figure_id",
            name="uq_source_figures_document_figure",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    figure_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    figure_order: Mapped[int] = mapped_column(Integer, nullable=False)
    figure_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_block_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON_DOCUMENT, nullable=True
    )
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asset_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


class SourceReferenceEntry(Base):
    __tablename__ = "source_reference_entries"
    __table_args__ = (
        CheckConstraint("year IS NULL OR year >= 0", name="year_non_negative"),
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_reference_entries_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "source_block_id"],
            [
                "source_blocks.collection_id",
                "source_blocks.build_id",
                "source_blocks.source_document_id",
                "source_blocks.block_id",
            ],
            name="fk_source_reference_entries_block",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "reference_id",
            name="uq_source_reference_entries_identity",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "reference_id",
            "source_document_id",
            name="uq_source_reference_entries_document",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reference_id: Mapped[str] = mapped_column(String(), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_reference: Mapped[str] = mapped_column(Text, nullable=False)
    reference_index: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_block_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


class SourceReferenceMention(Base):
    __tablename__ = "source_reference_mentions"
    __table_args__ = (
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
        CheckConstraint(
            "char_start IS NULL OR char_start >= 0", name="char_start_non_negative"
        ),
        CheckConstraint(
            "char_end IS NULL OR char_end >= 0", name="char_end_non_negative"
        ),
        CheckConstraint(
            "char_start IS NULL OR char_end IS NULL OR char_end >= char_start",
            name="char_range_ordered",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id"],
            [
                "source_documents.collection_id",
                "source_documents.build_id",
                "source_documents.source_document_id",
            ],
            name="fk_source_reference_mentions_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "source_document_id", "source_block_id"],
            [
                "source_blocks.collection_id",
                "source_blocks.build_id",
                "source_blocks.source_document_id",
                "source_blocks.block_id",
            ],
            name="fk_source_reference_mentions_block",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "reference_id", "source_document_id"],
            [
                "source_reference_entries.collection_id",
                "source_reference_entries.build_id",
                "source_reference_entries.reference_id",
                "source_reference_entries.source_document_id",
            ],
            name="fk_source_reference_mentions_entry",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "mention_id",
            name="uq_source_reference_mentions_identity",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mention_id: Mapped[str] = mapped_column(String(), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    citation_marker: Mapped[str] = mapped_column(Text, nullable=False)
    context_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_block_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


class SourceReferenceResolution(Base):
    __tablename__ = "source_reference_resolutions"
    __table_args__ = (
        CheckConstraint(
            "resolved_year IS NULL OR resolved_year >= 0",
            name="resolved_year_non_negative",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "reference_id"],
            [
                "source_reference_entries.collection_id",
                "source_reference_entries.build_id",
                "source_reference_entries.reference_id",
            ],
            name="fk_source_reference_resolutions_entry",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "resolution_id",
            name="uq_source_reference_resolutions_identity",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    resolution_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String(), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_authors_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_venue: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_doi: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_access_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


class SourceReferenceCandidate(Base):
    __tablename__ = "source_reference_candidates"
    __table_args__ = (
        CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 1",
            name="relevance_score_range",
        ),
        CheckConstraint("mention_count >= 0", name="mention_count_non_negative"),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "reference_id"],
            [
                "source_reference_entries.collection_id",
                "source_reference_entries.build_id",
                "source_reference_entries.reference_id",
            ],
            name="fk_source_reference_candidates_entry",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["collection_id", "build_id", "reference_id", "cited_by_document_id"],
            [
                "source_reference_entries.collection_id",
                "source_reference_entries.build_id",
                "source_reference_entries.reference_id",
                "source_reference_entries.source_document_id",
            ],
            name="fk_source_reference_candidates_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id",
            "build_id",
            "candidate_id",
            name="uq_source_reference_candidates_identity",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String(), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cited_by_document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False)
    representative_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_doi: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_access_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


__all__ = [
    "SourceBlock",
    "SourceBlockTextUnit",
    "SourceDocument",
    "SourceFigure",
    "SourceReferenceCandidate",
    "SourceReferenceEntry",
    "SourceReferenceMention",
    "SourceReferenceResolution",
    "SourceTable",
    "SourceTableCell",
    "SourceTableRow",
    "SourceTextUnit",
    "SourceTextUnitDocument",
]
