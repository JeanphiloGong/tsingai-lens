from __future__ import annotations

from typing import Any

from domain.source import SourceDocument, SourceDocumentTree
from infra.source.artifact_bundle import (
    source_block_payload,
    source_document_payload,
    source_figure_payload,
    source_table_cell_payload,
    source_table_payload,
    source_table_row_payload,
    source_text_unit_payload,
)
from repositories.source_artifact_repository import SourceArtifactRepository

SourceRecord = dict[str, Any]


async def load_collection_inputs(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
) -> tuple[tuple[SourceRecord, ...], tuple[SourceRecord, ...] | None]:
    source_documents = await _load_source_documents(
        collection_id, source_artifact_repository
    )
    documents = tuple(
        source_document_payload(document) for document in source_documents
    )
    text_units = tuple(
        source_text_unit_payload(text_unit)
        for document in source_documents
        for text_unit in document.text_units
    )
    return documents, text_units or None


async def load_blocks_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
) -> tuple[SourceRecord, ...]:
    source_documents = await _load_source_documents(
        collection_id, source_artifact_repository
    )
    return tuple(
        source_block_payload(block)
        for document in source_documents
        for block in document.blocks
    )


async def load_table_rows_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
) -> tuple[SourceRecord, ...]:
    source_documents = await _load_source_documents(
        collection_id, source_artifact_repository
    )
    return tuple(
        source_table_row_payload(row)
        for document in source_documents
        for row in document.table_rows
    )


async def load_table_cells_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
) -> tuple[SourceRecord, ...]:
    source_documents = await _load_source_documents(
        collection_id, source_artifact_repository
    )
    return tuple(
        source_table_cell_payload(cell)
        for document in source_documents
        for cell in document.table_cells
    )


async def load_figures_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
) -> tuple[SourceRecord, ...]:
    return tuple(
        source_figure_payload(figure)
        for figure in await source_artifact_repository.list_figures(collection_id)
    )


async def load_tables_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
) -> tuple[SourceRecord, ...]:
    source_documents = await _load_source_documents(
        collection_id, source_artifact_repository
    )
    return tuple(
        source_table_payload(table)
        for document in source_documents
        for table in document.tables
    )


async def load_document_tree(
    collection_id: str,
    document_id: str,
    source_artifact_repository: SourceArtifactRepository,
) -> SourceDocumentTree:
    return await source_artifact_repository.read_document_tree(
        collection_id,
        document_id,
    )


async def _load_source_documents(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
) -> tuple[SourceDocument, ...]:
    documents = await source_artifact_repository.read_collection_documents(
        collection_id
    )
    if not documents:
        raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
    return documents
