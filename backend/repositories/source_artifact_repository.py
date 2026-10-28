"""PostgreSQL repository for source artifact."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import (
    Any,
    Iterable,
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
    render_markdown_table,
    render_plain_table_text,
)
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
        artifact = {
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
                    metadata.get("source_format")
                    or metadata.get("file_type")
                    or "unknown"
                ),
                "parser_name": str(metadata.get("source_parser") or "unknown"),
                "parser_version": str(metadata.get("parser_version") or "unknown"),
                "source_fingerprint": source_fingerprint,
                "artifact_json": {
                    **artifact,
                    "references": {
                        "entries": [],
                        "mentions": [],
                        "resolutions": [],
                        "candidates": [],
                    },
                },
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
        missing = tuple(
            document_id for document_id in document_ids if document_id not in by_id
        )
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
                .order_by(
                    DocumentRow.document_order, DocumentPreparationRow.document_id
                )
            )
            if document_ids is not None:
                statement = statement.where(
                    DocumentPreparationRow.document_id.in_(document_ids)
                )
            rows = tuple(await session.scalars(statement))
        documents = []
        for row in rows:
            if not row.artifact_json:
                continue
            artifact = row.artifact_json
            document = artifact["document"]
            documents.append(
                SourceDocument(
                    document_id=document.get("document_id") or document.get("id") or "",
                    document_order=document.get("document_order", 0),
                    title=document.get("title", ""),
                    text=document.get("text", ""),
                    creation_date=document.get("creation_date"),
                    metadata=dict(document.get("metadata", {})),
                    text_units=tuple(
                        (
                            SourceTextUnit(
                                text_unit_id=item.get("text_unit_id")
                                or item.get("id")
                                or "",
                                text_unit_order=item.get("text_unit_order", 0),
                                text=item.get("text", ""),
                                n_tokens=item.get("n_tokens"),
                                document_ids=tuple(item.get("document_ids", ())),
                            )
                            for item in artifact.get("text_units", ())
                        )
                    ),
                    blocks=tuple(
                        (
                            SourceBlock(
                                block_id=item.get("block_id", ""),
                                document_id=item.get("document_id")
                                or item.get("id")
                                or "",
                                block_type=item.get("block_type", "paragraph"),
                                text=item.get("text", ""),
                                block_order=item.get("block_order", 0),
                                text_unit_ids=tuple(item.get("text_unit_ids", ())),
                                page=item.get("page"),
                                heading_path=item.get("heading_path"),
                                heading_level=item.get("heading_level"),
                            )
                            for item in artifact.get("blocks", ())
                        )
                    ),
                    tables=tuple(
                        (
                            SourceTable(
                                table_id=item.get("table_id", ""),
                                document_id=item.get("document_id", ""),
                                table_order=item.get("table_order", 0),
                                caption_text=item.get("caption_text"),
                                caption_block_id=item.get("caption_block_id"),
                                page=item.get("page"),
                                heading_path=item.get("heading_path"),
                                column_headers=tuple(item.get("column_headers", ())),
                                table_matrix=tuple(
                                    (
                                        tuple(row)
                                        for row in item.get("table_matrix") or ()
                                    )
                                ),
                                header_row_count=item.get("header_row_count", 1),
                                metadata=dict(item.get("metadata", {})),
                            )
                            for item in artifact.get("tables", ())
                        )
                    ),
                    table_rows=tuple(
                        (
                            SourceTableRow(
                                row_id=item.get("row_id", ""),
                                document_id=item.get("document_id", ""),
                                table_id=item.get("table_id", ""),
                                row_index=item.get("row_index", 0),
                                row_text=item.get("row_text", ""),
                                page=item.get("page"),
                                heading_path=item.get("heading_path"),
                            )
                            for item in artifact.get("table_rows", ())
                        )
                    ),
                    table_cells=tuple(
                        (
                            SourceTableCell(
                                cell_id=item.get("cell_id", ""),
                                document_id=item.get("document_id")
                                or item.get("id")
                                or "",
                                table_id=item.get("table_id", ""),
                                row_index=item.get("row_index", 0),
                                col_index=item.get("col_index", 0),
                                cell_text=item.get("cell_text", ""),
                                row_span=item.get("row_span", 1),
                                col_span=item.get("col_span", 1),
                                column_header=item.get("column_header", False),
                                row_header=item.get("row_header", False),
                                row_section=item.get("row_section", False),
                                header_path=item.get("header_path"),
                                page=item.get("page"),
                                unit_hint=item.get("unit_hint"),
                            )
                            for item in artifact.get("table_cells", ())
                        )
                    ),
                    figures=tuple(
                        (
                            SourceFigure(
                                figure_id=item.get("figure_id", ""),
                                document_id=item.get("document_id", ""),
                                figure_order=item.get("figure_order", 0),
                                figure_label=item.get("figure_label"),
                                caption_text=item.get("caption_text"),
                                caption_block_id=item.get("caption_block_id"),
                                page=item.get("page"),
                                heading_path=item.get("heading_path"),
                                image_path=item.get("image_path"),
                                image_mime_type=item.get("image_mime_type"),
                                image_width=item.get("image_width"),
                                image_height=item.get("image_height"),
                                asset_sha256=item.get("asset_sha256"),
                                image_size_bytes=item.get("image_size_bytes"),
                                metadata=dict(item.get("metadata", {})),
                            )
                            for item in artifact.get("figures", ())
                        )
                    ),
                )
            )
        return tuple(documents)

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
            artifact["references"] = {
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

    async def _read_references_for_document(
        self, document_id: str
    ) -> SourceReferenceSet:
        async with self.session_factory() as session:
            row = await session.get(DocumentPreparationRow, document_id)
        if row is None:
            return SourceReferenceSet()
        payload = row.artifact_json.get("references", {}) if row.artifact_json else {}
        return SourceReferenceSet(
            entries=tuple(
                (
                    SourceReferenceEntry(
                        reference_id=item.get("reference_id", ""),
                        document_id=item.get("document_id", ""),
                        raw_reference=item.get("raw_reference", ""),
                        reference_index=item.get("reference_index"),
                        title=item.get("title"),
                        authors_text=item.get("authors_text"),
                        year=item.get("year"),
                        doi=item.get("doi"),
                        source_block_id=item.get("source_block_id"),
                        page=item.get("page"),
                        confidence=item.get("confidence", 0.0),
                        metadata=dict(item.get("metadata", {})),
                    )
                    for item in payload.get("entries", [])
                )
            ),
            mentions=tuple(
                (
                    SourceReferenceMention(
                        mention_id=item.get("mention_id", ""),
                        document_id=item.get("document_id", ""),
                        reference_id=item.get("reference_id"),
                        citation_marker=item.get("citation_marker", ""),
                        context_text=item.get("context_text", ""),
                        source_block_id=item.get("source_block_id"),
                        page=item.get("page"),
                        confidence=item.get("confidence", 0.0),
                        metadata=dict(item.get("metadata", {})),
                    )
                    for item in payload.get("mentions", [])
                )
            ),
            resolutions=tuple(
                (
                    SourceReferenceResolution(
                        resolution_id=item.get("resolution_id", ""),
                        reference_id=item.get("reference_id", ""),
                        provider=item.get("provider", ""),
                        status=item.get("status", "unresolved"),
                        resolved_title=item.get("resolved_title"),
                        resolved_authors_text=item.get("resolved_authors_text"),
                        resolved_year=item.get("resolved_year"),
                        resolved_venue=item.get("resolved_venue"),
                        resolved_doi=item.get("resolved_doi"),
                        resolved_url=item.get("resolved_url"),
                        open_access_url=item.get("open_access_url"),
                        confidence=item.get("confidence", 0.0),
                        metadata=dict(item.get("metadata", {})),
                    )
                    for item in payload.get("resolutions", [])
                )
            ),
            candidates=tuple(
                (
                    SourceReferenceCandidate(
                        candidate_id=item.get("candidate_id", ""),
                        reference_id=item.get("reference_id", ""),
                        status=item.get("status", "metadata_only"),
                        relevance_score=item.get("relevance_score", 0.0),
                        relevance_reason=item.get("relevance_reason"),
                        cited_by_document_id=item.get("cited_by_document_id"),
                        mention_count=item.get("mention_count", 0),
                        representative_context=item.get("representative_context"),
                        resolved_doi=item.get("resolved_doi"),
                        resolved_url=item.get("resolved_url"),
                        open_access_url=item.get("open_access_url"),
                        metadata=dict(item.get("metadata", {})),
                    )
                    for item in payload.get("candidates", [])
                )
            ),
        )

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
        if any(
            item.reference_id not in reference_ids for item in references.resolutions
        ):
            raise ValueError("Reference resolutions must resolve within their document")
        if any(
            item.reference_id not in reference_ids for item in references.candidates
        ):
            raise ValueError("Reference candidates must resolve within their document")


def _merge_reference_sets(
    reference_sets: Iterable[SourceReferenceSet],
) -> SourceReferenceSet:
    sets = tuple(reference_sets)
    return SourceReferenceSet(
        entries=tuple(item for refs in sets for item in refs.entries),
        mentions=tuple(item for refs in sets for item in refs.mentions),
        resolutions=tuple(item for refs in sets for item in refs.resolutions),
        candidates=tuple(item for refs in sets for item in refs.candidates),
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


__all__ = ["SourceArtifactRepository"]
