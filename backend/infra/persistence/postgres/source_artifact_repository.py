"""PostgreSQL persistence for one canonical Source tree per document."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

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
)
from infra.persistence.postgres.models.document import Document as DocumentRow
from infra.persistence.postgres.models.document_preparation import DocumentPreparationRow


class PostgresSourceArtifactRepository:
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
        "text_units": [item.to_record() for item in document.text_units],
        "blocks": [item.to_record() for item in document.blocks],
        "tables": [item.to_record() for item in document.tables],
        "table_rows": [item.to_record() for item in document.table_rows],
        "table_cells": [item.to_record() for item in document.table_cells],
        "figures": [item.to_record() for item in document.figures],
    }


def _document_from_row(row: DocumentPreparationRow) -> SourceDocument:
    return _document_from_artifact(dict(row.artifact_json or {}))


def _document_from_artifact(artifact: dict[str, Any]) -> SourceDocument:
    document = dict(artifact.get("document") or {})
    for key in (
        "text_units",
        "blocks",
        "tables",
        "table_rows",
        "table_cells",
        "figures",
    ):
        document[key] = artifact.get(key) or []
    return SourceDocument.from_record(document)


def _references_payload(references: SourceReferenceSet) -> dict[str, list[dict[str, Any]]]:
    return {
        "entries": [item.to_record() for item in references.entries],
        "mentions": [item.to_record() for item in references.mentions],
        "resolutions": [item.to_record() for item in references.resolutions],
        "candidates": [item.to_record() for item in references.candidates],
    }


def _references_from_payload(value: Any) -> SourceReferenceSet:
    payload = dict(value or {})
    return SourceReferenceSet(
        entries=tuple(SourceReferenceEntry.from_record(item) for item in payload.get("entries") or []),
        mentions=tuple(SourceReferenceMention.from_record(item) for item in payload.get("mentions") or []),
        resolutions=tuple(SourceReferenceResolution.from_record(item) for item in payload.get("resolutions") or []),
        candidates=tuple(SourceReferenceCandidate.from_record(item) for item in payload.get("candidates") or []),
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


__all__ = ["PostgresSourceArtifactRepository"]
