from __future__ import annotations

from domain.source import (
    SourceDocument,
    SourceReferenceSet,
    build_source_document_tree,
)


class MemorySourceArtifactRepository:
    backend_name = "memory"

    def __init__(self, *, active_build_id: str = "build_test") -> None:
        self.active_build_id = active_build_id
        self._documents: dict[tuple[str, str], tuple[SourceDocument, ...]] = {}
        self._references: dict[tuple[str, str], SourceReferenceSet] = {}

    async def replace_collection_documents(
        self,
        collection_id: str,
        build_id: str,
        documents: tuple[SourceDocument, ...],
    ) -> None:
        self._documents[(collection_id, build_id)] = documents

    async def read_collection_documents(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> tuple[SourceDocument, ...]:
        selected_build_id = build_id or self.active_build_id
        return self._documents.get((collection_id, selected_build_id), ())

    async def replace_collection_references(
        self,
        collection_id: str,
        build_id: str,
        references: SourceReferenceSet,
    ) -> None:
        self._references[(collection_id, build_id)] = references

    async def read_collection_references(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> SourceReferenceSet:
        selected_build_id = build_id or self.active_build_id
        return self._references.get(
            (collection_id, selected_build_id), SourceReferenceSet()
        )

    async def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
        build_id: str | None = None,
    ):
        selected_build_id = build_id or self.active_build_id
        documents = self._documents.get((collection_id, selected_build_id), ())
        document = next(
            item for item in documents if item.document_id == document_id
        )
        return build_source_document_tree(
            collection_id=collection_id,
            document=document,
            blocks=document.blocks,
            tables=document.tables,
            figures=document.figures,
            references=self._references.get(
                (collection_id, selected_build_id),
                SourceReferenceSet(),
            ),
        )

    async def list_documents(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> list[SourceDocument]:
        selected_build_id = build_id or self.active_build_id
        return list(self._documents.get((collection_id, selected_build_id), ()))

    async def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list:
        documents = await self.list_documents(collection_id, build_id=build_id)
        return [
            item
            for document in documents
            if document_id is None or document.document_id == document_id
            for item in document.text_units
        ]

    async def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list:
        documents = await self.list_documents(collection_id, build_id=build_id)
        return [
            item
            for document in documents
            if document_id is None or document.document_id == document_id
            for item in document.blocks
        ]

    async def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list:
        documents = await self.list_documents(collection_id, build_id=build_id)
        return [
            item
            for document in documents
            if document_id is None or document.document_id == document_id
            for item in document.tables
        ]

    async def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list:
        documents = await self.list_documents(collection_id, build_id=build_id)
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
        build_id: str | None = None,
    ) -> list:
        documents = await self.list_documents(collection_id, build_id=build_id)
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
        build_id: str | None = None,
    ) -> list:
        documents = await self.list_documents(collection_id, build_id=build_id)
        return [
            item
            for document in documents
            if document_id is None or document.document_id == document_id
            for item in document.figures
        ]

    def activate(self, build_id: str) -> None:
        self.active_build_id = build_id


__all__ = ["MemorySourceArtifactRepository"]
