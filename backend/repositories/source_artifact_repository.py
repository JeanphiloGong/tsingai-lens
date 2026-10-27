"""PostgreSQL repository for source artifact."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import (
    Any,
    Iterable,
    Mapping,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.source import (
    SourceBlock,
    SourceDocument,
    SourceDocumentTree,
    SourceFigure,
    SourceReferenceCandidate,
    SourceReferenceEntry,
    SourceReferenceMention,
    SourceReferenceResolution,
    SourceReferenceSet,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
    build_source_document_tree,
    normalize_optional_text,
    render_markdown_table,
    render_plain_table_text,
    safe_int,
)
from domain.source.artifacts import _is_missing_value
from infra.persistence.postgres.models.document import Document as DocumentRow
from infra.persistence.postgres.models.document_preparation import (
    DocumentPreparationRow,
)


class SourceArtifactRepository:
    """Store the complete parsed artifact and its tree in one row."""

    backend_name = "postgres"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace_document(
        self,
        collection_id: str,
        document: SourceDocument,
    ) -> None:
        self._validate_document_aggregate(document)
        artifact = _artifact_payload(document)
        references = SourceReferenceSet()
        metadata = dict(document.metadata)
        serialized = _canonical_json(artifact)
        source_fingerprint = str(
            metadata.get("source_fingerprint")
            or hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        )
        now = datetime.now(timezone.utc)
        async with self.session_factory.begin() as session:
            owner = await session.get(DocumentRow, document.document_id)
            if owner is None or owner.collection_id != collection_id:
                raise FileNotFoundError(
                    f"collection document not found: {collection_id}/{document.document_id}"
                )
            row = await session.get(DocumentPreparationRow, document.document_id)
            values = {
                "document_id": document.document_id,
                "source_format": str(
                    metadata.get("source_format") or metadata.get("file_type") or "unknown"
                ),
                "parser_name": str(metadata.get("source_parser") or "unknown"),
                "parser_version": str(metadata.get("parser_version") or "unknown"),
                "source_fingerprint": source_fingerprint,
                "artifact_json": {**artifact, "references": _references_payload(references)},
                "updated_at": now,
            }
            if row is None:
                session.add(DocumentPreparationRow(created_at=now, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocument | None:
        documents = await self._read_documents(collection_id, (document_id,))
        return documents[0] if documents else None

    async def read_collection_documents(
        self,
        collection_id: str,
    ) -> tuple[SourceDocument, ...]:
        return await self._read_documents(collection_id)

    async def has_documents(self, collection_id: str) -> bool:
        async with self.session_factory() as session:
            document_id = await session.scalar(
                select(DocumentPreparationRow.document_id)
                .join(
                    DocumentRow,
                    DocumentRow.document_id == DocumentPreparationRow.document_id,
                )
                .where(
                    DocumentRow.collection_id == collection_id,
                    DocumentPreparationRow.artifact_json["document"]["document_id"]
                    .as_string()
                    .is_not(None),
                )
                .limit(1)
            )
        return document_id is not None

    async def read_documents(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> tuple[SourceDocument, ...]:
        if not document_ids:
            return ()
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("source document IDs must be unique")
        documents = await self._read_documents(collection_id, document_ids)
        by_id = {document.document_id: document for document in documents}
        missing = tuple(document_id for document_id in document_ids if document_id not in by_id)
        if missing:
            raise FileNotFoundError("source documents not found: " + ", ".join(missing))
        return tuple(by_id[document_id] for document_id in document_ids)

    async def _read_documents(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[SourceDocument, ...]:
        async with self.session_factory() as session:
            statement = (
                select(DocumentPreparationRow)
                .join(
                    DocumentRow,
                    DocumentRow.document_id == DocumentPreparationRow.document_id,
                )
                .where(
                    DocumentRow.collection_id == collection_id,
                )
                .order_by(DocumentRow.document_order, DocumentPreparationRow.document_id)
            )
            if document_ids is not None:
                statement = statement.where(
                    DocumentPreparationRow.document_id.in_(document_ids)
                )
            rows = tuple(await session.scalars(statement))
        return tuple(_document_from_row(row) for row in rows if row.artifact_json)

    async def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocumentTree:
        document = await self.read_document(collection_id, document_id)
        if document is None:
            raise FileNotFoundError(
                f"source document not found: {collection_id}/{document_id}"
            )
        references = await self._read_references_for_document(document_id)
        return build_source_document_tree(
            collection_id=collection_id,
            document=document,
            blocks=document.blocks,
            tables=document.tables,
            figures=document.figures,
            references=references,
        )

    async def list_documents(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        document_ids: tuple[str, ...] | None = None,
    ) -> list[SourceDocument]:
        selected = document_ids
        if document_id is not None:
            selected = (document_id,)
        return list(await self._read_documents(collection_id, selected))

    async def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        document_ids: tuple[str, ...] | None = None,
    ) -> list[SourceTextUnit]:
        documents = await self.list_documents(
            collection_id,
            document_id,
            document_ids=document_ids,
        )
        return [item for document in documents for item in document.text_units]

    async def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        document_ids: tuple[str, ...] | None = None,
    ) -> list[SourceBlock]:
        documents = await self.list_documents(
            collection_id,
            document_id,
            document_ids=document_ids,
        )
        return [item for document in documents for item in document.blocks]

    async def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        document_ids: tuple[str, ...] | None = None,
    ) -> list[SourceTable]:
        documents = await self.list_documents(
            collection_id,
            document_id,
            document_ids=document_ids,
        )
        return [item for document in documents for item in document.tables]

    async def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
        *,
        document_ids: tuple[str, ...] | None = None,
    ) -> list[SourceTableRow]:
        documents = await self.list_documents(collection_id, document_ids=document_ids)
        return [
            item
            for document in documents
            for item in document.table_rows
            if table_id is None or item.table_id == table_id
        ]

    async def list_table_cells(
        self,
        collection_id: str,
        table_id: str | None = None,
        row_index: int | None = None,
        *,
        document_ids: tuple[str, ...] | None = None,
    ) -> list[SourceTableCell]:
        documents = await self.list_documents(collection_id, document_ids=document_ids)
        return [
            item
            for document in documents
            for item in document.table_cells
            if (table_id is None or item.table_id == table_id)
            and (row_index is None or item.row_index == row_index)
        ]

    async def list_figures(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        document_ids: tuple[str, ...] | None = None,
    ) -> list[SourceFigure]:
        documents = await self.list_documents(
            collection_id,
            document_id,
            document_ids=document_ids,
        )
        return [item for document in documents for item in document.figures]

    async def replace_document_references(
        self,
        document_id: str,
        references: SourceReferenceSet,
    ) -> None:
        self._validate_references(document_id, references)
        async with self.session_factory.begin() as session:
            row = await session.get(DocumentPreparationRow, document_id)
            if row is None or not row.artifact_json:
                raise FileNotFoundError(f"source document not found: {document_id}")
            artifact = dict(row.artifact_json or {})
            artifact["references"] = _references_payload(references)
            row.artifact_json = artifact
            row.updated_at = datetime.now(timezone.utc)

    async def read_collection_references(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> SourceReferenceSet:
        documents = await self.list_documents(collection_id, document_ids=document_ids)
        reference_sets = [
            await self._read_references_for_document(document.document_id)
            for document in documents
        ]
        return _merge_reference_sets(reference_sets)

    async def _read_references_for_document(self, document_id: str) -> SourceReferenceSet:
        async with self.session_factory() as session:
            row = await session.get(DocumentPreparationRow, document_id)
        if row is None:
            return SourceReferenceSet()
        return _references_from_payload(dict(row.artifact_json or {}).get("references"))

    @staticmethod
    def _validate_document_aggregate(document: SourceDocument) -> None:
        document_id = document.document_id
        if any(document_id not in item.document_ids for item in document.text_units):
            raise ValueError("Source text units must belong to their document")
        for items in (
            document.blocks,
            document.tables,
            document.table_rows,
            document.table_cells,
            document.figures,
        ):
            if any(item.document_id != document_id for item in items):
                raise ValueError("Source children must belong to their document")

    @staticmethod
    def _validate_references(document_id: str, references: SourceReferenceSet) -> None:
        if any(item.document_id != document_id for item in references.entries):
            raise ValueError("Reference entries must belong to their document")
        if any(item.document_id != document_id for item in references.mentions):
            raise ValueError("Reference mentions must belong to their document")
        reference_ids = {item.reference_id for item in references.entries}
        if any(item.reference_id not in reference_ids for item in references.resolutions):
            raise ValueError("Reference resolutions must resolve within their document")
        if any(item.reference_id not in reference_ids for item in references.candidates):
            raise ValueError("Reference candidates must resolve within their document")


def _artifact_payload(document: SourceDocument) -> dict[str, Any]:
    return {
        "document": {
            "document_id": document.document_id,
            "document_order": document.document_order,
            "title": document.title,
            "text": document.text,
            "creation_date": document.creation_date,
            "metadata": dict(document.metadata),
        },
        "text_units": [
            {
                "id": item.text_unit_id,
                "text_unit_order": item.text_unit_order,
                "text": item.text,
                "n_tokens": item.n_tokens,
                "document_ids": list(item.document_ids),
            }
            for item in document.text_units
        ],
        "blocks": [
            {
                "block_id": item.block_id,
                "document_id": item.document_id,
                "block_type": str(item.block_type),
                "text": item.text,
                "block_order": item.block_order,
                "text_unit_ids": list(item.text_unit_ids),
                "page": item.page,
                "heading_path": item.heading_path,
                "heading_level": item.heading_level,
            }
            for item in document.blocks
        ],
        "tables": [
            {
                "table_id": item.table_id,
                "document_id": item.document_id,
                "table_order": item.table_order,
                "caption_text": item.caption_text,
                "caption_block_id": item.caption_block_id,
                "page": item.page,
                "heading_path": item.heading_path,
                "row_count": item.row_count,
                "col_count": item.col_count,
                "header_row_count": item.header_row_count,
                "column_headers": list(item.column_headers),
                "table_matrix": [list(row) for row in item.table_matrix],
                "table_markdown": render_markdown_table(
                    [list(row) for row in item.table_matrix],
                    list(item.column_headers),
                    header_row_count=item.header_row_count,
                ),
                "table_text": render_plain_table_text(
                    [list(row) for row in item.table_matrix]
                ),
                "metadata": dict(item.metadata),
            }
            for item in document.tables
        ],
        "table_rows": [
            {
                "row_id": item.row_id,
                "document_id": item.document_id,
                "table_id": item.table_id,
                "row_index": item.row_index,
                "row_text": item.row_text,
                "page": item.page,
                "heading_path": item.heading_path,
            }
            for item in document.table_rows
        ],
        "table_cells": [
            {
                "cell_id": item.cell_id,
                "document_id": item.document_id,
                "id": item.document_id,
                "table_id": item.table_id,
                "row_index": item.row_index,
                "col_index": item.col_index,
                "cell_text": item.cell_text,
                "row_span": item.row_span,
                "col_span": item.col_span,
                "column_header": item.column_header,
                "row_header": item.row_header,
                "row_section": item.row_section,
                "header_path": item.header_path,
                "page": item.page,
                "unit_hint": item.unit_hint,
            }
            for item in document.table_cells
        ],
        "figures": [
            {
                "figure_id": item.figure_id,
                "document_id": item.document_id,
                "figure_order": item.figure_order,
                "figure_label": item.figure_label,
                "caption_text": item.caption_text,
                "caption_block_id": item.caption_block_id,
                "page": item.page,
                "heading_path": item.heading_path,
                "image_path": item.image_path,
                "image_mime_type": item.image_mime_type,
                "image_width": item.image_width,
                "image_height": item.image_height,
                "asset_sha256": item.asset_sha256,
                "image_size_bytes": item.image_size_bytes,
                "metadata": dict(item.metadata),
            }
            for item in document.figures
        ],
    }


def _document_from_row(row: DocumentPreparationRow) -> SourceDocument:
    return _document_from_artifact(dict(row.artifact_json or {}))


def _document_from_artifact(artifact: dict[str, Any]) -> SourceDocument:
    document = dict(artifact.get("document") or {})
    return SourceDocument(
        document_id=str(document.get("document_id") or document.get("id") or ""),
        document_order=safe_int(document.get("document_order")) or 0,
        title=str(document.get("title") or ""),
        text=str(document.get("text") or ""),
        creation_date=normalize_optional_text(document.get("creation_date")),
        metadata=_mapping(document.get("metadata")),
        text_units=tuple(
            (
                SourceTextUnit(
                    text_unit_id=str(item.get("text_unit_id") or item.get("id") or ""),
                    text_unit_order=safe_int(item.get("text_unit_order")) or 0,
                    text=str(item.get("text") or ""),
                    n_tokens=safe_int(item.get("n_tokens")),
                    document_ids=_string_tuple(item.get("document_ids")),
                )
                for item in artifact.get("text_units") or ()
                if isinstance(item, Mapping)
            )
        ),
        blocks=tuple(
            (
                SourceBlock(
                    block_id=str(item.get("block_id") or ""),
                    document_id=str(item.get("document_id") or item.get("id") or ""),
                    block_type=str(item.get("block_type") or "paragraph"),
                    text=str(item.get("text") or ""),
                    block_order=safe_int(item.get("block_order")) or 0,
                    text_unit_ids=_string_tuple(item.get("text_unit_ids")),
                    page=safe_int(item.get("page")),
                    heading_path=normalize_optional_text(item.get("heading_path")),
                    heading_level=safe_int(item.get("heading_level")),
                )
                for item in artifact.get("blocks") or ()
                if isinstance(item, Mapping)
            )
        ),
        tables=tuple(
            (
                SourceTable(
                    table_id=str(item.get("table_id") or ""),
                    document_id=str(item.get("document_id") or ""),
                    table_order=safe_int(item.get("table_order")) or 0,
                    caption_text=normalize_optional_text(item.get("caption_text")),
                    caption_block_id=normalize_optional_text(
                        item.get("caption_block_id")
                    ),
                    page=safe_int(item.get("page")),
                    heading_path=normalize_optional_text(item.get("heading_path")),
                    column_headers=_string_tuple(item.get("column_headers")),
                    table_matrix=_table_matrix_tuple(item.get("table_matrix")),
                    header_row_count=max(
                        0,
                        (
                            safe_int(item.get("header_row_count"))
                            if safe_int(item.get("header_row_count")) is not None
                            else 1
                        ),
                    ),
                    metadata=_mapping(item.get("metadata")),
                )
                for item in artifact.get("tables") or ()
                if isinstance(item, Mapping)
            )
        ),
        table_rows=tuple(
            (
                SourceTableRow(
                    row_id=str(item.get("row_id") or ""),
                    document_id=str(item.get("document_id") or ""),
                    table_id=str(item.get("table_id") or ""),
                    row_index=safe_int(item.get("row_index")) or 0,
                    row_text=str(item.get("row_text") or ""),
                    page=safe_int(item.get("page")),
                    heading_path=normalize_optional_text(item.get("heading_path")),
                )
                for item in artifact.get("table_rows") or ()
                if isinstance(item, Mapping)
            )
        ),
        table_cells=tuple(
            (
                SourceTableCell(
                    cell_id=str(item.get("cell_id") or ""),
                    document_id=str(item.get("document_id") or item.get("id") or ""),
                    table_id=str(item.get("table_id") or ""),
                    row_index=safe_int(item.get("row_index")) or 0,
                    col_index=safe_int(item.get("col_index")) or 0,
                    cell_text=str(item.get("cell_text") or ""),
                    row_span=max(
                        1,
                        (
                            safe_int(item.get("row_span"))
                            if safe_int(item.get("row_span")) is not None
                            else 1
                        ),
                    ),
                    col_span=max(
                        1,
                        (
                            safe_int(item.get("col_span"))
                            if safe_int(item.get("col_span")) is not None
                            else 1
                        ),
                    ),
                    column_header=bool(item.get("column_header")),
                    row_header=bool(item.get("row_header")),
                    row_section=bool(item.get("row_section")),
                    header_path=normalize_optional_text(item.get("header_path")),
                    page=safe_int(item.get("page")),
                    unit_hint=normalize_optional_text(item.get("unit_hint")),
                )
                for item in artifact.get("table_cells") or ()
                if isinstance(item, Mapping)
            )
        ),
        figures=tuple(
            (
                SourceFigure(
                    figure_id=str(item.get("figure_id") or ""),
                    document_id=str(item.get("document_id") or ""),
                    figure_order=safe_int(item.get("figure_order")) or 0,
                    figure_label=normalize_optional_text(item.get("figure_label")),
                    caption_text=normalize_optional_text(item.get("caption_text")),
                    caption_block_id=normalize_optional_text(
                        item.get("caption_block_id")
                    ),
                    page=safe_int(item.get("page")),
                    heading_path=normalize_optional_text(item.get("heading_path")),
                    image_path=normalize_optional_text(item.get("image_path")),
                    image_mime_type=normalize_optional_text(
                        item.get("image_mime_type")
                    ),
                    image_width=safe_int(item.get("image_width")),
                    image_height=safe_int(item.get("image_height")),
                    asset_sha256=normalize_optional_text(item.get("asset_sha256")),
                    image_size_bytes=safe_int(item.get("image_size_bytes")),
                    metadata=_mapping(item.get("metadata")),
                )
                for item in artifact.get("figures") or ()
                if isinstance(item, Mapping)
            )
        ),
    )


def _references_payload(references: SourceReferenceSet) -> dict[str, list[dict[str, Any]]]:
    return {
        "entries": [
            {
                "reference_id": item.reference_id,
                "document_id": item.document_id,
                "raw_reference": item.raw_reference,
                "reference_index": item.reference_index,
                "title": item.title,
                "authors_text": item.authors_text,
                "year": item.year,
                "doi": item.doi,
                "source_block_id": item.source_block_id,
                "page": item.page,
                "confidence": item.confidence,
                "metadata": dict(item.metadata),
            }
            for item in references.entries
        ],
        "mentions": [
            {
                "mention_id": item.mention_id,
                "document_id": item.document_id,
                "reference_id": item.reference_id,
                "citation_marker": item.citation_marker,
                "context_text": item.context_text,
                "source_block_id": item.source_block_id,
                "page": item.page,
                "confidence": item.confidence,
                "metadata": dict(item.metadata),
            }
            for item in references.mentions
        ],
        "resolutions": [
            {
                "resolution_id": item.resolution_id,
                "reference_id": item.reference_id,
                "provider": item.provider,
                "status": item.status,
                "resolved_title": item.resolved_title,
                "resolved_authors_text": item.resolved_authors_text,
                "resolved_year": item.resolved_year,
                "resolved_venue": item.resolved_venue,
                "resolved_doi": item.resolved_doi,
                "resolved_url": item.resolved_url,
                "open_access_url": item.open_access_url,
                "confidence": item.confidence,
                "metadata": dict(item.metadata),
            }
            for item in references.resolutions
        ],
        "candidates": [
            {
                "candidate_id": item.candidate_id,
                "reference_id": item.reference_id,
                "status": item.status,
                "relevance_score": item.relevance_score,
                "relevance_reason": item.relevance_reason,
                "cited_by_document_id": item.cited_by_document_id,
                "mention_count": item.mention_count,
                "representative_context": item.representative_context,
                "resolved_doi": item.resolved_doi,
                "resolved_url": item.resolved_url,
                "open_access_url": item.open_access_url,
                "metadata": dict(item.metadata),
            }
            for item in references.candidates
        ],
    }


def _references_from_payload(value: Any) -> SourceReferenceSet:
    payload = dict(value or {})
    return SourceReferenceSet(
        entries=tuple(
            SourceReferenceEntry(
                reference_id=str(item.get("reference_id") or ""),
                document_id=str(item.get("document_id") or ""),
                raw_reference=str(item.get("raw_reference") or ""),
                reference_index=normalize_optional_text(item.get("reference_index")),
                title=normalize_optional_text(item.get("title")),
                authors_text=normalize_optional_text(item.get("authors_text")),
                year=safe_int(item.get("year")),
                doi=normalize_optional_text(item.get("doi")),
                source_block_id=normalize_optional_text(item.get("source_block_id")),
                page=safe_int(item.get("page")),
                confidence=float(item.get("confidence") or 0.0),
                metadata=_mapping(item.get("metadata")),
            )
            for item in payload.get("entries") or []
        ),
        mentions=tuple(
            SourceReferenceMention(
                mention_id=str(item.get("mention_id") or ""),
                document_id=str(item.get("document_id") or ""),
                reference_id=normalize_optional_text(item.get("reference_id")),
                citation_marker=str(item.get("citation_marker") or ""),
                context_text=str(item.get("context_text") or ""),
                source_block_id=normalize_optional_text(item.get("source_block_id")),
                page=safe_int(item.get("page")),
                confidence=float(item.get("confidence") or 0.0),
                metadata=_mapping(item.get("metadata")),
            )
            for item in payload.get("mentions") or []
        ),
        resolutions=tuple(
            SourceReferenceResolution(
                resolution_id=str(item.get("resolution_id") or ""),
                reference_id=str(item.get("reference_id") or ""),
                provider=str(item.get("provider") or ""),
                status=str(item.get("status") or "unresolved"),
                resolved_title=normalize_optional_text(item.get("resolved_title")),
                resolved_authors_text=normalize_optional_text(
                    item.get("resolved_authors_text")
                ),
                resolved_year=safe_int(item.get("resolved_year")),
                resolved_venue=normalize_optional_text(item.get("resolved_venue")),
                resolved_doi=normalize_optional_text(item.get("resolved_doi")),
                resolved_url=normalize_optional_text(item.get("resolved_url")),
                open_access_url=normalize_optional_text(item.get("open_access_url")),
                confidence=float(item.get("confidence") or 0.0),
                metadata=_mapping(item.get("metadata")),
            )
            for item in payload.get("resolutions") or []
        ),
        candidates=tuple(
            SourceReferenceCandidate(
                candidate_id=str(item.get("candidate_id") or ""),
                reference_id=str(item.get("reference_id") or ""),
                status=str(item.get("status") or "metadata_only"),
                relevance_score=float(item.get("relevance_score") or 0.0),
                relevance_reason=normalize_optional_text(item.get("relevance_reason")),
                cited_by_document_id=normalize_optional_text(
                    item.get("cited_by_document_id")
                ),
                mention_count=safe_int(item.get("mention_count")) or 0,
                representative_context=normalize_optional_text(
                    item.get("representative_context")
                ),
                resolved_doi=normalize_optional_text(item.get("resolved_doi")),
                resolved_url=normalize_optional_text(item.get("resolved_url")),
                open_access_url=normalize_optional_text(item.get("open_access_url")),
                metadata=_mapping(item.get("metadata")),
            )
            for item in payload.get("candidates") or []
        ),
    )


def _merge_reference_sets(reference_sets: Iterable[SourceReferenceSet]) -> SourceReferenceSet:
    sets = tuple(reference_sets)
    return SourceReferenceSet(
        entries=tuple(item for refs in sets for item in refs.entries),
        mentions=tuple(item for refs in sets for item in refs.mentions),
        resolutions=tuple(item for refs in sets for item in refs.resolutions),
        candidates=tuple(item for refs in sets for item in refs.candidates),
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


__all__ = ['SourceArtifactRepository']


def _string_tuple(value: Any) -> tuple[str, ...]:
    if _is_missing_value(value):
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return (text,)
            return _string_tuple(parsed)
        return (text,)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        return tuple(str(item) for item in value if not _is_missing_value(item))
    return (str(value),)


def _table_matrix_tuple(value: Any) -> tuple[tuple[str, ...], ...]:
    if _is_missing_value(value):
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return ((text,),)
        return _table_matrix_tuple(parsed)
    if not isinstance(value, Iterable) or isinstance(value, (bytes, Mapping)):
        return ((str(value),),)

    rows = []
    for row in value:
        if isinstance(row, str) or not isinstance(row, Iterable):
            rows.append((str(row),))
        else:
            rows.append(tuple(str(cell) for cell in row))
    return tuple(rows)


def _mapping(value: Any) -> Mapping[str, Any]:
    if _is_missing_value(value):
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}
