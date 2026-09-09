from __future__ import annotations

from typing import Protocol

from domain.source import (
    SourceBlock,
    SourceDocument,
    SourceDocumentTree,
    SourceFigure,
    SourceReferenceSet,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
)


class SourceArtifactRepository(Protocol):
    backend_name: str

    async def replace_document(
        self,
        collection_id: str,
        document: SourceDocument,
    ) -> None: ...

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocument | None: ...

    async def read_collection_documents(
        self,
        collection_id: str,
    ) -> tuple[SourceDocument, ...]: ...

    async def read_documents(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> tuple[SourceDocument, ...]: ...

    async def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocumentTree: ...

    async def list_documents(
        self,
        collection_id: str,
    ) -> list[SourceDocument]: ...

    async def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceTextUnit]: ...

    async def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceBlock]: ...

    async def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceTable]: ...

    async def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
    ) -> list[SourceTableRow]: ...

    async def list_table_cells(
        self,
        collection_id: str,
        table_id: str | None = None,
        row_index: int | None = None,
    ) -> list[SourceTableCell]: ...

    async def replace_document_references(
        self,
        document_id: str,
        references: SourceReferenceSet,
    ) -> None: ...

    async def read_collection_references(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> SourceReferenceSet: ...

    async def list_figures(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceFigure]: ...
