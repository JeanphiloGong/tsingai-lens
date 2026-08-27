"""Current parsed Source structure owned by individual documents."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.persistence.postgres.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        CheckConstraint("document_order >= 0", name="document_order_non_negative"),
    )

    source_document_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    collection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("collections.collection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    creation_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        _JSON_DOCUMENT, nullable=False
    )


class SourceTextUnit(Base):
    __tablename__ = "source_text_units"
    __table_args__ = (
        CheckConstraint("text_unit_order >= 0", name="text_unit_order_non_negative"),
        CheckConstraint(
            "n_tokens IS NULL OR n_tokens >= 0", name="n_tokens_non_negative"
        ),
    )

    source_document_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("source_documents.source_document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    text_unit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    text_unit_order: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    n_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SourceBlock(Base):
    __tablename__ = "source_blocks"
    __table_args__ = (
        CheckConstraint("block_order >= 0", name="block_order_non_negative"),
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
    )

    source_document_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("source_documents.source_document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    block_id: Mapped[str] = mapped_column(String(), primary_key=True)
    block_type: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    block_order: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SourceBlockTextUnit(Base):
    __tablename__ = "source_block_text_units"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_document_id", "block_id"],
            ["source_blocks.source_document_id", "source_blocks.block_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_document_id", "text_unit_id"],
            [
                "source_text_units.source_document_id",
                "source_text_units.text_unit_id",
            ],
            ondelete="CASCADE",
        ),
    )

    source_document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    block_id: Mapped[str] = mapped_column(String(), primary_key=True)
    text_unit_id: Mapped[str] = mapped_column(String(128), primary_key=True)


class SourceTable(Base):
    __tablename__ = "source_tables"
    __table_args__ = (
        CheckConstraint("table_order >= 0", name="table_order_non_negative"),
        CheckConstraint("header_row_count >= 0", name="header_row_count_non_negative"),
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
    )

    source_document_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("source_documents.source_document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    table_id: Mapped[str] = mapped_column(String(), primary_key=True)
    table_order: Mapped[int] = mapped_column(Integer, nullable=False)
    caption_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_block_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    header_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
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
            ["source_document_id", "table_id"],
            ["source_tables.source_document_id", "source_tables.table_id"],
            ondelete="CASCADE",
        ),
    )

    source_document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    row_id: Mapped[str] = mapped_column(String(), primary_key=True)
    table_id: Mapped[str] = mapped_column(String(), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    row_text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceTableCell(Base):
    __tablename__ = "source_table_cells"
    __table_args__ = (
        CheckConstraint("row_index >= 0", name="row_index_non_negative"),
        CheckConstraint("col_index >= 0", name="col_index_non_negative"),
        CheckConstraint("row_span >= 1", name="row_span_positive"),
        CheckConstraint("col_span >= 1", name="col_span_positive"),
        CheckConstraint("page IS NULL OR page >= 0", name="page_non_negative"),
        ForeignKeyConstraint(
            ["source_document_id", "table_id"],
            ["source_tables.source_document_id", "source_tables.table_id"],
            ondelete="CASCADE",
        ),
    )

    source_document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    cell_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    table_id: Mapped[str] = mapped_column(String(), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    col_index: Mapped[int] = mapped_column(Integer, nullable=False)
    cell_text: Mapped[str] = mapped_column(Text, nullable=False)
    row_span: Mapped[int] = mapped_column(Integer, nullable=False)
    col_span: Mapped[int] = mapped_column(Integer, nullable=False)
    column_header: Mapped[bool] = mapped_column(Boolean, nullable=False)
    row_header: Mapped[bool] = mapped_column(Boolean, nullable=False)
    row_section: Mapped[bool] = mapped_column(Boolean, nullable=False)
    header_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    )

    source_document_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("source_documents.source_document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    figure_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    figure_order: Mapped[int] = mapped_column(Integer, nullable=False)
    figure_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_block_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    )

    source_document_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("source_documents.source_document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    reference_id: Mapped[str] = mapped_column(String(), primary_key=True)
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
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    source_document_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("source_documents.source_document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    mention_id: Mapped[str] = mapped_column(String(), primary_key=True)
    reference_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    citation_marker: Mapped[str] = mapped_column(Text, nullable=False)
    context_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_block_id: Mapped[str | None] = mapped_column(String(), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    )

    resolution_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    reference_id: Mapped[str] = mapped_column(String(), nullable=False, index=True)
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
    )

    candidate_id: Mapped[str] = mapped_column(String(), primary_key=True)
    reference_id: Mapped[str] = mapped_column(String(), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cited_by_document_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
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
]
