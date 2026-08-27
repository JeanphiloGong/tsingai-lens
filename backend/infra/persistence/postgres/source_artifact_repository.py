"""PostgreSQL persistence for versioned Source document structure."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select
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
    assemble_source_documents,
    build_source_document_tree,
)
from infra.persistence.postgres.models.build import (
    CollectionActiveBuild,
    CollectionBuild,
)
from infra.persistence.postgres.models.collection import CollectionFile
from infra.persistence.postgres.models.document import CollectionDocument
from infra.persistence.postgres.models.source import (
    SourceBlock as SourceBlockRow,
    SourceBlockTextUnit,
    SourceDocument as SourceDocumentRow,
    SourceFigure as SourceFigureRow,
    SourceReferenceCandidate as SourceReferenceCandidateRow,
    SourceReferenceEntry as SourceReferenceEntryRow,
    SourceReferenceMention as SourceReferenceMentionRow,
    SourceReferenceResolution as SourceReferenceResolutionRow,
    SourceTable as SourceTableModel,
    SourceTableCell as SourceTableCellRow,
    SourceTableRow as SourceTableRowModel,
    SourceTextUnit as SourceTextUnitRow,
    SourceTextUnitDocument,
)


class PostgresSourceArtifactRepository:
    """Store immutable Source structure under an explicit collection build."""

    backend_name = "postgres"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace_collection_documents(
        self,
        collection_id: str,
        build_id: str,
        documents: tuple[SourceDocument, ...],
    ) -> None:
        text_units = tuple(
            {
                item.text_unit_id: item
                for document in documents
                for item in document.text_units
            }.values()
        )
        blocks = tuple(item for document in documents for item in document.blocks)
        tables = tuple(item for document in documents for item in document.tables)
        table_rows = tuple(
            item for document in documents for item in document.table_rows
        )
        table_cells = tuple(
            item for document in documents for item in document.table_cells
        )
        figures = tuple(item for document in documents for item in document.figures)
        async with self.session_factory.begin() as session:
            build = await self._require_build(
                session, collection_id, build_id
            )
            if build.status not in {"queued", "building"}:
                raise ValueError(f"collection build is not writable: {build_id}")
            lineage = await self._resolve_document_lineage(
                session,
                collection_id,
                documents,
            )
            await session.execute(
                delete(SourceDocumentRow).where(SourceDocumentRow.build_id == build_id)
            )
            session.add_all(
                SourceDocumentRow(
                    build_id=build_id,
                    source_document_id=document.document_id,
                    collection_id=collection_id,
                    collection_document_id=lineage[document.document_id][0],
                    document_version_id=lineage[document.document_id][1],
                    document_order=document.document_order,
                    title=document.title,
                    text=document.text,
                    creation_date=document.creation_date,
                    metadata_json=dict(document.metadata),
                )
                for document in documents
            )
            await session.flush()
            session.add_all(
                SourceTextUnitRow(
                    build_id=build_id,
                    text_unit_id=text_unit.text_unit_id,
                    collection_id=collection_id,
                    text_unit_order=text_unit.text_unit_order,
                    text=text_unit.text,
                    n_tokens=text_unit.n_tokens,
                )
                for text_unit in text_units
            )
            await session.flush()
            session.add_all(
                SourceTextUnitDocument(
                    build_id=build_id,
                    text_unit_id=text_unit.text_unit_id,
                    source_document_id=document_id,
                    collection_id=collection_id,
                )
                for text_unit in text_units
                for document_id in text_unit.document_ids
            )
            session.add_all(
                SourceBlockRow(
                    build_id=build_id,
                    block_id=block.block_id,
                    collection_id=collection_id,
                    source_document_id=block.document_id,
                    block_type=str(block.block_type),
                    text=block.text,
                    block_order=block.block_order,
                    page=block.page,
                    heading_path=block.heading_path,
                    heading_level=block.heading_level,
                )
                for block in blocks
            )
            await session.flush()
            session.add_all(
                SourceBlockTextUnit(
                    build_id=build_id,
                    block_id=block.block_id,
                    text_unit_id=text_unit_id,
                    collection_id=collection_id,
                )
                for block in blocks
                for text_unit_id in block.text_unit_ids
            )
            session.add_all(
                SourceTableModel(
                    build_id=build_id,
                    table_id=table.table_id,
                    collection_id=collection_id,
                    source_document_id=table.document_id,
                    table_order=table.table_order,
                    caption_text=table.caption_text,
                    caption_block_id=table.caption_block_id,
                    page=table.page,
                    heading_path=table.heading_path,
                    header_row_count=table.header_row_count,
                    column_headers=list(table.column_headers),
                    table_matrix=[list(row) for row in table.table_matrix],
                    metadata_json=dict(table.metadata),
                )
                for table in tables
            )
            await session.flush()
            session.add_all(
                SourceTableRowModel(
                    build_id=build_id,
                    row_id=row.row_id,
                    collection_id=collection_id,
                    source_document_id=row.document_id,
                    table_id=row.table_id,
                    row_index=row.row_index,
                    row_text=row.row_text,
                    page=row.page,
                    heading_path=row.heading_path,
                )
                for row in table_rows
            )
            session.add_all(
                SourceTableCellRow(
                    build_id=build_id,
                    cell_id=cell.cell_id,
                    collection_id=collection_id,
                    source_document_id=cell.document_id,
                    table_id=cell.table_id,
                    row_index=cell.row_index,
                    col_index=cell.col_index,
                    cell_text=cell.cell_text,
                    row_span=cell.row_span,
                    col_span=cell.col_span,
                    column_header=cell.column_header,
                    row_header=cell.row_header,
                    row_section=cell.row_section,
                    header_path=cell.header_path,
                    page=cell.page,
                    unit_hint=cell.unit_hint,
                )
                for cell in table_cells
            )
            session.add_all(
                SourceFigureRow(
                    build_id=build_id,
                    figure_id=figure.figure_id,
                    collection_id=collection_id,
                    source_document_id=figure.document_id,
                    figure_order=figure.figure_order,
                    figure_label=figure.figure_label,
                    caption_text=figure.caption_text,
                    caption_block_id=figure.caption_block_id,
                    page=figure.page,
                    heading_path=figure.heading_path,
                    image_storage_key=figure.image_path,
                    image_mime_type=figure.image_mime_type,
                    image_width=figure.image_width,
                    image_height=figure.image_height,
                    asset_sha256=figure.asset_sha256,
                    image_size_bytes=figure.image_size_bytes,
                    metadata_json=dict(figure.metadata),
                )
                for figure in figures
            )

    async def read_collection_documents(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> tuple[SourceDocument, ...]:
        if build_id is None:
            async with self.session_factory() as session:
                build_id = await self._resolve_read_build(
                    session, collection_id, None
                )
            if build_id is None:
                return ()
        return assemble_source_documents(
            documents=tuple(
                await self.list_documents(collection_id, build_id=build_id)
            ),
            text_units=tuple(
                await self.list_text_units(collection_id, build_id=build_id)
            ),
            blocks=tuple(
                await self.list_blocks(collection_id, build_id=build_id)
            ),
            tables=tuple(
                await self.list_tables(collection_id, build_id=build_id)
            ),
            table_rows=tuple(
                await self.list_table_rows(collection_id, build_id=build_id)
            ),
            table_cells=tuple(
                await self.list_table_cells(collection_id, build_id=build_id)
            ),
            figures=tuple(
                await self.list_figures(collection_id, build_id=build_id)
            ),
        )

    async def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
        build_id: str | None = None,
    ) -> SourceDocumentTree:
        if build_id is None:
            async with self.session_factory() as session:
                build_id = await self._resolve_read_build(
                    session, collection_id, None
                )
            if build_id is None:
                raise FileNotFoundError(
                    f"source document not found: {collection_id}/{document_id}"
                )
        document = next(
            (
                item
                for item in await self.read_collection_documents(
                    collection_id, build_id=build_id
                )
                if item.document_id == document_id
            ),
            None,
        )
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
            references=await self.read_collection_references(
                collection_id, build_id=build_id
            ),
        )

    async def list_documents(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> list[SourceDocument]:
        async with self.session_factory() as session:
            resolved_build_id = await self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return []
            text_units_by_document = await self._text_units_by_document(
                session, collection_id, resolved_build_id
            )
            rows = await session.scalars(
                select(SourceDocumentRow)
                .where(
                    SourceDocumentRow.collection_id == collection_id,
                    SourceDocumentRow.build_id == resolved_build_id,
                )
                .order_by(
                    SourceDocumentRow.document_order,
                    SourceDocumentRow.source_document_id,
                )
            )
            return [
                SourceDocument.from_record(
                    {
                        "document_id": row.source_document_id,
                        "document_order": row.document_order,
                        "title": row.title,
                        "text": row.text,
                        "text_unit_ids": text_units_by_document.get(
                            row.source_document_id, ()
                        ),
                        "creation_date": row.creation_date,
                        "metadata": row.metadata_json,
                    }
                )
                for row in rows
            ]

    async def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTextUnit]:
        async with self.session_factory() as session:
            resolved_build_id = await self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return []
            documents_by_text_unit = await self._documents_by_text_unit(
                session, collection_id, resolved_build_id
            )
            statement = select(SourceTextUnitRow).where(
                SourceTextUnitRow.collection_id == collection_id,
                SourceTextUnitRow.build_id == resolved_build_id,
            )
            if document_id is not None:
                statement = statement.join(
                    SourceTextUnitDocument,
                    (
                        (SourceTextUnitDocument.build_id == SourceTextUnitRow.build_id)
                        & (
                            SourceTextUnitDocument.text_unit_id
                            == SourceTextUnitRow.text_unit_id
                        )
                    ),
                ).where(SourceTextUnitDocument.source_document_id == document_id)
            rows = await session.scalars(
                statement.order_by(
                    SourceTextUnitRow.text_unit_order,
                    SourceTextUnitRow.text_unit_id,
                )
            )
            return [
                SourceTextUnit.from_record(
                    {
                        "text_unit_id": row.text_unit_id,
                        "text_unit_order": row.text_unit_order,
                        "text": row.text,
                        "n_tokens": row.n_tokens,
                        "document_ids": documents_by_text_unit.get(
                            row.text_unit_id, ()
                        ),
                    }
                )
                for row in rows
            ]

    async def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceBlock]:
        async with self.session_factory() as session:
            resolved_build_id = await self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return []
            text_units_by_block = await self._text_units_by_block(
                session, collection_id, resolved_build_id
            )
            statement = select(SourceBlockRow).where(
                SourceBlockRow.collection_id == collection_id,
                SourceBlockRow.build_id == resolved_build_id,
            )
            if document_id is not None:
                statement = statement.where(
                    SourceBlockRow.source_document_id == document_id
                )
            rows = await session.scalars(
                statement.order_by(
                    SourceBlockRow.source_document_id,
                    SourceBlockRow.block_order,
                    SourceBlockRow.block_id,
                )
            )
            return [
                SourceBlock.from_record(
                    {
                        "block_id": row.block_id,
                        "document_id": row.source_document_id,
                        "block_type": row.block_type,
                        "text": row.text,
                        "block_order": row.block_order,
                        "text_unit_ids": text_units_by_block.get(row.block_id, ()),
                        "page": row.page,
                        "heading_path": row.heading_path,
                        "heading_level": row.heading_level,
                    }
                )
                for row in rows
            ]

    async def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTable]:
        async with self.session_factory() as session:
            resolved_build_id = await self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return []
            statement = select(SourceTableModel).where(
                SourceTableModel.collection_id == collection_id,
                SourceTableModel.build_id == resolved_build_id,
            )
            if document_id is not None:
                statement = statement.where(
                    SourceTableModel.source_document_id == document_id
                )
            rows = await session.scalars(
                statement.order_by(
                    SourceTableModel.source_document_id,
                    SourceTableModel.table_order,
                    SourceTableModel.table_id,
                )
            )
            return [
                SourceTable.from_record(
                    {
                        "table_id": row.table_id,
                        "document_id": row.source_document_id,
                        "table_order": row.table_order,
                        "caption_text": row.caption_text,
                        "caption_block_id": row.caption_block_id,
                        "page": row.page,
                        "heading_path": row.heading_path,
                        "header_row_count": row.header_row_count,
                        "column_headers": row.column_headers,
                        "table_matrix": row.table_matrix,
                        "metadata": row.metadata_json,
                    }
                )
                for row in rows
            ]

    async def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTableRow]:
        async with self.session_factory() as session:
            resolved_build_id = await self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return []
            statement = select(SourceTableRowModel).where(
                SourceTableRowModel.collection_id == collection_id,
                SourceTableRowModel.build_id == resolved_build_id,
            )
            if table_id is not None:
                statement = statement.where(SourceTableRowModel.table_id == table_id)
            rows = await session.scalars(
                statement.order_by(
                    SourceTableRowModel.source_document_id,
                    SourceTableRowModel.table_id,
                    SourceTableRowModel.row_index,
                    SourceTableRowModel.row_id,
                )
            )
            return [
                SourceTableRow.from_record(
                    {
                        "row_id": row.row_id,
                        "document_id": row.source_document_id,
                        "table_id": row.table_id,
                        "row_index": row.row_index,
                        "row_text": row.row_text,
                        "page": row.page,
                        "heading_path": row.heading_path,
                    }
                )
                for row in rows
            ]

    async def list_table_cells(
        self,
        collection_id: str,
        table_id: str | None = None,
        row_index: int | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTableCell]:
        async with self.session_factory() as session:
            resolved_build_id = await self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return []
            statement = select(SourceTableCellRow).where(
                SourceTableCellRow.collection_id == collection_id,
                SourceTableCellRow.build_id == resolved_build_id,
            )
            if table_id is not None:
                statement = statement.where(SourceTableCellRow.table_id == table_id)
            if row_index is not None:
                statement = statement.where(SourceTableCellRow.row_index == row_index)
            rows = await session.scalars(
                statement.order_by(
                    SourceTableCellRow.source_document_id,
                    SourceTableCellRow.table_id,
                    SourceTableCellRow.row_index,
                    SourceTableCellRow.col_index,
                    SourceTableCellRow.cell_id,
                )
            )
            return [
                SourceTableCell.from_record(
                    {
                        "cell_id": row.cell_id,
                        "document_id": row.source_document_id,
                        "table_id": row.table_id,
                        "row_index": row.row_index,
                        "col_index": row.col_index,
                        "cell_text": row.cell_text,
                        "row_span": row.row_span,
                        "col_span": row.col_span,
                        "column_header": row.column_header,
                        "row_header": row.row_header,
                        "row_section": row.row_section,
                        "header_path": row.header_path,
                        "page": row.page,
                        "unit_hint": row.unit_hint,
                    }
                )
                for row in rows
            ]

    async def list_figures(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceFigure]:
        async with self.session_factory() as session:
            resolved_build_id = await self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return []
            statement = select(SourceFigureRow).where(
                SourceFigureRow.collection_id == collection_id,
                SourceFigureRow.build_id == resolved_build_id,
            )
            if document_id is not None:
                statement = statement.where(
                    SourceFigureRow.source_document_id == document_id
                )
            rows = await session.scalars(
                statement.order_by(
                    SourceFigureRow.source_document_id,
                    SourceFigureRow.figure_order,
                    SourceFigureRow.figure_id,
                )
            )
            return [
                SourceFigure.from_record(
                    {
                        "figure_id": row.figure_id,
                        "document_id": row.source_document_id,
                        "figure_order": row.figure_order,
                        "figure_label": row.figure_label,
                        "caption_text": row.caption_text,
                        "caption_block_id": row.caption_block_id,
                        "page": row.page,
                        "heading_path": row.heading_path,
                        "image_path": row.image_storage_key,
                        "image_mime_type": row.image_mime_type,
                        "image_width": row.image_width,
                        "image_height": row.image_height,
                        "asset_sha256": row.asset_sha256,
                        "image_size_bytes": row.image_size_bytes,
                        "metadata": row.metadata_json,
                    }
                )
                for row in rows
            ]

    async def replace_collection_references(
        self,
        collection_id: str,
        build_id: str,
        references: SourceReferenceSet,
    ) -> None:
        async with self.session_factory.begin() as session:
            build = await self._require_build(
                session, collection_id, build_id
            )
            if build.status not in {"queued", "building"}:
                raise ValueError(f"collection build is not writable: {build_id}")
            for model in (
                SourceReferenceCandidateRow,
                SourceReferenceResolutionRow,
                SourceReferenceMentionRow,
                SourceReferenceEntryRow,
            ):
                await session.execute(delete(model).where(model.build_id == build_id))
            session.add_all(
                SourceReferenceEntryRow(
                    build_id=build_id,
                    reference_id=entry.reference_id,
                    collection_id=collection_id,
                    source_document_id=entry.document_id,
                    raw_reference=entry.raw_reference,
                    reference_index=entry.reference_index,
                    title=entry.title,
                    authors_text=entry.authors_text,
                    year=entry.year,
                    doi=entry.doi,
                    source_block_id=entry.source_block_id,
                    page=entry.page,
                    confidence=entry.confidence,
                    metadata_json=dict(entry.metadata),
                )
                for entry in references.entries
            )
            await session.flush()
            session.add_all(
                SourceReferenceMentionRow(
                    build_id=build_id,
                    mention_id=mention.mention_id,
                    collection_id=collection_id,
                    source_document_id=mention.document_id,
                    reference_id=mention.reference_id,
                    citation_marker=mention.citation_marker,
                    context_text=mention.context_text,
                    source_block_id=mention.source_block_id,
                    page=mention.page,
                    confidence=mention.confidence,
                    metadata_json=dict(mention.metadata),
                )
                for mention in references.mentions
            )
            session.add_all(
                SourceReferenceResolutionRow(
                    build_id=build_id,
                    resolution_id=resolution.resolution_id,
                    collection_id=collection_id,
                    reference_id=resolution.reference_id,
                    provider=resolution.provider,
                    status=resolution.status,
                    resolved_title=resolution.resolved_title,
                    resolved_authors_text=resolution.resolved_authors_text,
                    resolved_year=resolution.resolved_year,
                    resolved_venue=resolution.resolved_venue,
                    resolved_doi=resolution.resolved_doi,
                    resolved_url=resolution.resolved_url,
                    open_access_url=resolution.open_access_url,
                    confidence=resolution.confidence,
                    metadata_json=dict(resolution.metadata),
                )
                for resolution in references.resolutions
            )
            session.add_all(
                SourceReferenceCandidateRow(
                    build_id=build_id,
                    candidate_id=candidate.candidate_id,
                    collection_id=collection_id,
                    reference_id=candidate.reference_id,
                    status=candidate.status,
                    relevance_score=candidate.relevance_score,
                    relevance_reason=candidate.relevance_reason,
                    cited_by_document_id=candidate.cited_by_document_id,
                    mention_count=candidate.mention_count,
                    representative_context=candidate.representative_context,
                    resolved_doi=candidate.resolved_doi,
                    resolved_url=candidate.resolved_url,
                    open_access_url=candidate.open_access_url,
                    metadata_json=dict(candidate.metadata),
                )
                for candidate in references.candidates
            )

    async def read_collection_references(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> SourceReferenceSet:
        async with self.session_factory() as session:
            resolved_build_id = await self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return SourceReferenceSet()
            entries = await session.scalars(
                select(SourceReferenceEntryRow)
                .where(
                    SourceReferenceEntryRow.collection_id == collection_id,
                    SourceReferenceEntryRow.build_id == resolved_build_id,
                )
                .order_by(
                    SourceReferenceEntryRow.source_document_id,
                    SourceReferenceEntryRow.reference_index.asc().nulls_first(),
                    SourceReferenceEntryRow.reference_id,
                )
            )
            mentions = await session.scalars(
                select(SourceReferenceMentionRow)
                .where(
                    SourceReferenceMentionRow.collection_id == collection_id,
                    SourceReferenceMentionRow.build_id == resolved_build_id,
                )
                .order_by(
                    SourceReferenceMentionRow.source_document_id,
                    SourceReferenceMentionRow.source_block_id.asc().nulls_first(),
                    SourceReferenceMentionRow.mention_id,
                )
            )
            resolutions = await session.scalars(
                select(SourceReferenceResolutionRow)
                .where(
                    SourceReferenceResolutionRow.collection_id == collection_id,
                    SourceReferenceResolutionRow.build_id == resolved_build_id,
                )
                .order_by(
                    SourceReferenceResolutionRow.reference_id,
                    SourceReferenceResolutionRow.provider,
                    SourceReferenceResolutionRow.resolution_id,
                )
            )
            candidates = await session.scalars(
                select(SourceReferenceCandidateRow)
                .where(
                    SourceReferenceCandidateRow.collection_id == collection_id,
                    SourceReferenceCandidateRow.build_id == resolved_build_id,
                )
                .order_by(
                    SourceReferenceCandidateRow.relevance_score.desc(),
                    SourceReferenceCandidateRow.candidate_id,
                )
            )
            return SourceReferenceSet(
                entries=tuple(
                    SourceReferenceEntry.from_record(
                        {
                            "reference_id": row.reference_id,
                            "document_id": row.source_document_id,
                            "raw_reference": row.raw_reference,
                            "reference_index": row.reference_index,
                            "title": row.title,
                            "authors_text": row.authors_text,
                            "year": row.year,
                            "doi": row.doi,
                            "source_block_id": row.source_block_id,
                            "page": row.page,
                            "confidence": row.confidence,
                            "metadata": row.metadata_json,
                        }
                    )
                    for row in entries
                ),
                mentions=tuple(
                    SourceReferenceMention.from_record(
                        {
                            "mention_id": row.mention_id,
                            "document_id": row.source_document_id,
                            "reference_id": row.reference_id,
                            "citation_marker": row.citation_marker,
                            "context_text": row.context_text,
                            "source_block_id": row.source_block_id,
                            "page": row.page,
                            "confidence": row.confidence,
                            "metadata": row.metadata_json,
                        }
                    )
                    for row in mentions
                ),
                resolutions=tuple(
                    SourceReferenceResolution.from_record(
                        {
                            "resolution_id": row.resolution_id,
                            "reference_id": row.reference_id,
                            "provider": row.provider,
                            "status": row.status,
                            "resolved_title": row.resolved_title,
                            "resolved_authors_text": row.resolved_authors_text,
                            "resolved_year": row.resolved_year,
                            "resolved_venue": row.resolved_venue,
                            "resolved_doi": row.resolved_doi,
                            "resolved_url": row.resolved_url,
                            "open_access_url": row.open_access_url,
                            "confidence": row.confidence,
                            "metadata": row.metadata_json,
                        }
                    )
                    for row in resolutions
                ),
                candidates=tuple(
                    SourceReferenceCandidate.from_record(
                        {
                            "candidate_id": row.candidate_id,
                            "reference_id": row.reference_id,
                            "status": row.status,
                            "relevance_score": row.relevance_score,
                            "relevance_reason": row.relevance_reason,
                            "cited_by_document_id": row.cited_by_document_id,
                            "mention_count": row.mention_count,
                            "representative_context": row.representative_context,
                            "resolved_doi": row.resolved_doi,
                            "resolved_url": row.resolved_url,
                            "open_access_url": row.open_access_url,
                            "metadata": row.metadata_json,
                        }
                    )
                    for row in candidates
                ),
            )

    @staticmethod
    async def _require_build(
        session: AsyncSession,
        collection_id: str,
        build_id: str,
    ) -> CollectionBuild:
        build = await session.get(CollectionBuild, build_id)
        if build is None or build.collection_id != collection_id:
            raise FileNotFoundError(
                f"collection build not found: {collection_id}/{build_id}"
            )
        return build

    @staticmethod
    async def _resolve_read_build(
        session: AsyncSession,
        collection_id: str,
        build_id: str | None,
    ) -> str | None:
        if build_id is not None:
            await PostgresSourceArtifactRepository._require_build(
                session, collection_id, build_id
            )
            return build_id
        return await session.scalar(
            select(CollectionActiveBuild.build_id).where(
                CollectionActiveBuild.collection_id == collection_id
            )
        )

    @staticmethod
    async def _resolve_document_lineage(
        session: AsyncSession,
        collection_id: str,
        documents: tuple[SourceDocument, ...],
    ) -> dict[str, tuple[str, str]]:
        file_rows = (
            await session.execute(
            select(
                CollectionFile.stored_filename,
                CollectionDocument.collection_document_id,
                CollectionDocument.document_version_id,
            )
            .join(
                CollectionDocument,
                CollectionDocument.collection_document_id
                == CollectionFile.collection_document_id,
            )
            .where(CollectionFile.collection_id == collection_id)
            )
        ).all()
        lineage_by_filename: dict[str, list[tuple[str, str]]] = {}
        for stored_filename, collection_document_id, document_version_id in file_rows:
            lineage_by_filename.setdefault(str(stored_filename), []).append(
                (str(collection_document_id), str(document_version_id))
            )
        result: dict[str, tuple[str, str]] = {}
        for document in documents:
            source_path = str(document.metadata.get("source_path") or "").strip()
            filename = Path(source_path).name
            matches = lineage_by_filename.get(filename, [])
            unique_matches = list(dict.fromkeys(matches))
            if len(unique_matches) != 1:
                raise ValueError(
                    "source document must resolve to exactly one collection document: "
                    f"{document.document_id}/{source_path}"
                )
            result[document.document_id] = unique_matches[0]
        return result

    @staticmethod
    async def _documents_by_text_unit(
        session: AsyncSession, collection_id: str, build_id: str
    ) -> dict[str, tuple[str, ...]]:
        rows = await session.execute(
            select(
                SourceTextUnitDocument.text_unit_id,
                SourceTextUnitDocument.source_document_id,
            )
            .where(
                SourceTextUnitDocument.collection_id == collection_id,
                SourceTextUnitDocument.build_id == build_id,
            )
            .order_by(
                SourceTextUnitDocument.text_unit_id,
                SourceTextUnitDocument.source_document_id,
            )
        )
        return _group_pairs(rows)

    @staticmethod
    async def _text_units_by_document(
        session: AsyncSession, collection_id: str, build_id: str
    ) -> dict[str, tuple[str, ...]]:
        rows = await session.execute(
            select(
                SourceTextUnitDocument.source_document_id,
                SourceTextUnitDocument.text_unit_id,
            )
            .join(
                SourceTextUnitRow,
                (SourceTextUnitRow.build_id == SourceTextUnitDocument.build_id)
                & (
                    SourceTextUnitRow.text_unit_id
                    == SourceTextUnitDocument.text_unit_id
                ),
            )
            .where(
                SourceTextUnitDocument.collection_id == collection_id,
                SourceTextUnitDocument.build_id == build_id,
            )
            .order_by(
                SourceTextUnitDocument.source_document_id,
                SourceTextUnitRow.text_unit_order,
                SourceTextUnitDocument.text_unit_id,
            )
        )
        return _group_pairs(rows)

    @staticmethod
    async def _text_units_by_block(
        session: AsyncSession, collection_id: str, build_id: str
    ) -> dict[str, tuple[str, ...]]:
        rows = await session.execute(
            select(SourceBlockTextUnit.block_id, SourceBlockTextUnit.text_unit_id)
            .join(
                SourceTextUnitRow,
                (SourceTextUnitRow.build_id == SourceBlockTextUnit.build_id)
                & (SourceTextUnitRow.text_unit_id == SourceBlockTextUnit.text_unit_id),
            )
            .where(
                SourceBlockTextUnit.collection_id == collection_id,
                SourceBlockTextUnit.build_id == build_id,
            )
            .order_by(
                SourceBlockTextUnit.block_id,
                SourceTextUnitRow.text_unit_order,
                SourceBlockTextUnit.text_unit_id,
            )
        )
        return _group_pairs(rows)


def _group_pairs(rows) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for key, value in rows:
        grouped.setdefault(str(key), []).append(str(value))
    return {key: tuple(values) for key, values in grouped.items()}


__all__ = ["PostgresSourceArtifactRepository"]
