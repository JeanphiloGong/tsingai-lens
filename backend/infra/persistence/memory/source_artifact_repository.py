"""In-memory persistence for current document Source aggregates."""

from __future__ import annotations

from copy import deepcopy

from domain.source import (
    SourceDocument,
    SourceReferenceSet,
    build_source_document_tree,
)


class MemorySourceArtifactRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self._documents: dict[tuple[str, str], SourceDocument] = {}
        self._references: dict[str, SourceReferenceSet] = {}

    async def replace_document(
        self,
        collection_id: str,
        document: SourceDocument,
    ) -> None:
        self._documents[(collection_id, document.document_id)] = deepcopy(document)

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocument | None:
        document = self._documents.get((collection_id, document_id))
        return deepcopy(document) if document is not None else None

    async def read_collection_documents(
        self,
        collection_id: str,
    ) -> tuple[SourceDocument, ...]:
        return tuple(
            deepcopy(document)
            for (owner_collection_id, _), document in sorted(
                self._documents.items(),
                key=lambda item: (
                    item[1].document_order,
                    item[1].document_id,
                ),
            )
            if owner_collection_id == collection_id
        )

    async def read_documents(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> tuple[SourceDocument, ...]:
        if not document_ids:
            return ()
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("source document IDs must be unique")
        missing = tuple(
            document_id
            for document_id in document_ids
            if (collection_id, document_id) not in self._documents
        )
        if missing:
            raise FileNotFoundError(
                "source documents not found: " + ", ".join(missing)
            )
        return tuple(
            deepcopy(self._documents[(collection_id, document_id)])
            for document_id in document_ids
        )

    async def replace_document_references(
        self,
        document_id: str,
        references: SourceReferenceSet,
    ) -> None:
        self._references[document_id] = deepcopy(references)

    async def read_collection_references(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> SourceReferenceSet:
        collection_document_ids = {
            document_id
            for owner_collection_id, document_id in self._documents
            if owner_collection_id == collection_id
        }
        if document_ids is not None:
            collection_document_ids &= set(document_ids)
        reference_sets = [
            self._references[document_id]
            for document_id in sorted(collection_document_ids)
            if document_id in self._references
        ]
        return SourceReferenceSet(
            entries=tuple(item for refs in reference_sets for item in refs.entries),
            mentions=tuple(item for refs in reference_sets for item in refs.mentions),
            resolutions=tuple(
                item for refs in reference_sets for item in refs.resolutions
            ),
            candidates=tuple(
                item for refs in reference_sets for item in refs.candidates
            ),
        )

    async def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
    ):
        document = await self.read_document(collection_id, document_id)
        if document is None:
            raise FileNotFoundError(
                f"source document not found: {collection_id}/{document_id}"
            )
        return build_source_document_tree(
            collection_id=collection_id,
            document=document,
            blocks=document.blocks,
            tables=document.tables,
            figures=document.figures,
            references=deepcopy(
                self._references.get(document_id, SourceReferenceSet())
            ),
        )

    async def list_documents(self, collection_id: str) -> list[SourceDocument]:
        return list(await self.read_collection_documents(collection_id))

    async def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list:
        return [
            item
            for document in await self.read_collection_documents(collection_id)
            if document_id is None or document.document_id == document_id
            for item in document.text_units
        ]

    async def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list:
        return [
            item
            for document in await self.read_collection_documents(collection_id)
            if document_id is None or document.document_id == document_id
            for item in document.blocks
        ]

    async def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list:
        return [
            item
            for document in await self.read_collection_documents(collection_id)
            if document_id is None or document.document_id == document_id
            for item in document.tables
        ]

    async def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
    ) -> list:
        return [
            item
            for document in await self.read_collection_documents(collection_id)
            for item in document.table_rows
            if table_id is None or item.table_id == table_id
        ]

    async def list_table_cells(
        self,
        collection_id: str,
        table_id: str | None = None,
        row_index: int | None = None,
    ) -> list:
        return [
            item
            for document in await self.read_collection_documents(collection_id)
            for item in document.table_cells
            if (table_id is None or item.table_id == table_id)
            and (row_index is None or item.row_index == row_index)
        ]

    async def list_figures(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list:
        return [
            item
            for document in await self.read_collection_documents(collection_id)
            if document_id is None or document.document_id == document_id
            for item in document.figures
        ]


__all__ = ["MemorySourceArtifactRepository"]
