"""PostgreSQL persistence for each document's current parsed Source tree."""

from __future__ import annotations

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
from infra.persistence.postgres.models.document import Document as DocumentRow
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
)


class PostgresSourceArtifactRepository:
    """Store exactly one current Source aggregate for each collection document."""

    backend_name = "postgres"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace_document(
        self,
        collection_id: str,
        document: SourceDocument,
    ) -> None:
        self._validate_document_aggregate(document)
        async with self.session_factory.begin() as session:
            row = await session.get(DocumentRow, document.document_id)
            if row is None or row.collection_id != collection_id:
                raise FileNotFoundError(
                    f"collection document not found: {collection_id}/{document.document_id}"
                )
            await session.execute(
                delete(SourceDocumentRow).where(
                    SourceDocumentRow.source_document_id == document.document_id,
                    SourceDocumentRow.collection_id == collection_id,
                )
            )
            session.add(
                SourceDocumentRow(
                    source_document_id=document.document_id,
                    collection_id=collection_id,
                    document_order=document.document_order,
                    title=document.title,
                    text=document.text,
                    creation_date=document.creation_date,
                    metadata_json=dict(document.metadata),
                )
            )
            await session.flush()
            session.add_all(
                SourceTextUnitRow(
                    source_document_id=document.document_id,
                    text_unit_id=item.text_unit_id,
                    text_unit_order=item.text_unit_order,
                    text=item.text,
                    n_tokens=item.n_tokens,
                )
                for item in document.text_units
            )
            session.add_all(
                SourceBlockRow(
                    source_document_id=document.document_id,
                    block_id=item.block_id,
                    block_type=str(item.block_type),
                    text=item.text,
                    block_order=item.block_order,
                    page=item.page,
                    heading_path=item.heading_path,
                    heading_level=item.heading_level,
                )
                for item in document.blocks
            )
            await session.flush()
            session.add_all(
                SourceBlockTextUnit(
                    source_document_id=document.document_id,
                    block_id=block.block_id,
                    text_unit_id=text_unit_id,
                )
                for block in document.blocks
                for text_unit_id in block.text_unit_ids
            )
            session.add_all(
                SourceTableModel(
                    source_document_id=document.document_id,
                    table_id=item.table_id,
                    table_order=item.table_order,
                    caption_text=item.caption_text,
                    caption_block_id=item.caption_block_id,
                    page=item.page,
                    heading_path=item.heading_path,
                    header_row_count=item.header_row_count,
                    column_headers=list(item.column_headers),
                    table_matrix=[list(row) for row in item.table_matrix],
                    metadata_json=dict(item.metadata),
                )
                for item in document.tables
            )
            await session.flush()
            session.add_all(
                SourceTableRowModel(
                    source_document_id=document.document_id,
                    row_id=item.row_id,
                    table_id=item.table_id,
                    row_index=item.row_index,
                    row_text=item.row_text,
                    page=item.page,
                    heading_path=item.heading_path,
                )
                for item in document.table_rows
            )
            session.add_all(
                SourceTableCellRow(
                    source_document_id=document.document_id,
                    cell_id=item.cell_id,
                    table_id=item.table_id,
                    row_index=item.row_index,
                    col_index=item.col_index,
                    cell_text=item.cell_text,
                    row_span=item.row_span,
                    col_span=item.col_span,
                    column_header=item.column_header,
                    row_header=item.row_header,
                    row_section=item.row_section,
                    header_path=item.header_path,
                    page=item.page,
                    unit_hint=item.unit_hint,
                )
                for item in document.table_cells
            )
            session.add_all(
                SourceFigureRow(
                    source_document_id=document.document_id,
                    figure_id=item.figure_id,
                    figure_order=item.figure_order,
                    figure_label=item.figure_label,
                    caption_text=item.caption_text,
                    caption_block_id=item.caption_block_id,
                    page=item.page,
                    heading_path=item.heading_path,
                    image_storage_key=item.image_path,
                    image_mime_type=item.image_mime_type,
                    image_width=item.image_width,
                    image_height=item.image_height,
                    asset_sha256=item.asset_sha256,
                    image_size_bytes=item.image_size_bytes,
                    metadata_json=dict(item.metadata),
                )
                for item in document.figures
            )

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocument | None:
        documents = await self._read_documents(collection_id, document_id=document_id)
        return documents[0] if documents else None

    async def read_collection_documents(
        self,
        collection_id: str,
    ) -> tuple[SourceDocument, ...]:
        return await self._read_documents(collection_id)

    async def _read_documents(
        self,
        collection_id: str,
        *,
        document_id: str | None = None,
    ) -> tuple[SourceDocument, ...]:
        return assemble_source_documents(
            documents=tuple(await self.list_documents(collection_id, document_id)),
            text_units=tuple(await self.list_text_units(collection_id, document_id)),
            blocks=tuple(await self.list_blocks(collection_id, document_id)),
            tables=tuple(await self.list_tables(collection_id, document_id)),
            table_rows=tuple(
                item
                for item in await self.list_table_rows(collection_id)
                if document_id is None or item.document_id == document_id
            ),
            table_cells=tuple(
                item
                for item in await self.list_table_cells(collection_id)
                if document_id is None or item.document_id == document_id
            ),
            figures=tuple(await self.list_figures(collection_id, document_id)),
        )

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
        references = await self.read_collection_references(collection_id)
        document_reference_ids = {
            item.reference_id
            for item in references.entries
            if item.document_id == document_id
        }
        return build_source_document_tree(
            collection_id=collection_id,
            document=document,
            blocks=document.blocks,
            tables=document.tables,
            figures=document.figures,
            references=SourceReferenceSet(
                entries=tuple(
                    item for item in references.entries if item.document_id == document_id
                ),
                mentions=tuple(
                    item for item in references.mentions if item.document_id == document_id
                ),
                resolutions=tuple(
                    item
                    for item in references.resolutions
                    if item.reference_id in document_reference_ids
                ),
                candidates=tuple(
                    item
                    for item in references.candidates
                    if item.reference_id in document_reference_ids
                ),
            ),
        )

    async def list_documents(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceDocument]:
        async with self.session_factory() as session:
            statement = select(SourceDocumentRow).where(
                SourceDocumentRow.collection_id == collection_id
            )
            if document_id is not None:
                statement = statement.where(
                    SourceDocumentRow.source_document_id == document_id
                )
            rows = await session.scalars(
                statement.order_by(
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
    ) -> list[SourceTextUnit]:
        async with self.session_factory() as session:
            statement = self._source_statement(SourceTextUnitRow, collection_id)
            if document_id is not None:
                statement = statement.where(
                    SourceTextUnitRow.source_document_id == document_id
                )
            rows = await session.scalars(
                statement.order_by(
                    SourceTextUnitRow.source_document_id,
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
                        "document_ids": (row.source_document_id,),
                    }
                )
                for row in rows
            ]

    async def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceBlock]:
        async with self.session_factory() as session:
            text_units_by_block = await self._text_units_by_block(
                session, collection_id, document_id
            )
            statement = self._source_statement(SourceBlockRow, collection_id)
            if document_id is not None:
                statement = statement.where(SourceBlockRow.source_document_id == document_id)
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
                        "text_unit_ids": text_units_by_block.get(
                            (row.source_document_id, row.block_id), ()
                        ),
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
    ) -> list[SourceTable]:
        async with self.session_factory() as session:
            statement = self._source_statement(SourceTableModel, collection_id)
            if document_id is not None:
                statement = statement.where(SourceTableModel.source_document_id == document_id)
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
    ) -> list[SourceTableRow]:
        async with self.session_factory() as session:
            statement = self._source_statement(SourceTableRowModel, collection_id)
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
    ) -> list[SourceTableCell]:
        async with self.session_factory() as session:
            statement = self._source_statement(SourceTableCellRow, collection_id)
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
    ) -> list[SourceFigure]:
        async with self.session_factory() as session:
            statement = self._source_statement(SourceFigureRow, collection_id)
            if document_id is not None:
                statement = statement.where(SourceFigureRow.source_document_id == document_id)
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

    async def replace_document_references(
        self,
        document_id: str,
        references: SourceReferenceSet,
    ) -> None:
        self._validate_references(document_id, references)
        async with self.session_factory.begin() as session:
            if await session.get(SourceDocumentRow, document_id) is None:
                raise FileNotFoundError(f"source document not found: {document_id}")
            old_reference_ids = tuple(
                await session.scalars(
                    select(SourceReferenceEntryRow.reference_id).where(
                        SourceReferenceEntryRow.source_document_id == document_id
                    )
                )
            )
            if old_reference_ids:
                await session.execute(
                    delete(SourceReferenceCandidateRow).where(
                        SourceReferenceCandidateRow.reference_id.in_(old_reference_ids)
                    )
                )
                await session.execute(
                    delete(SourceReferenceResolutionRow).where(
                        SourceReferenceResolutionRow.reference_id.in_(old_reference_ids)
                    )
                )
            await session.execute(
                delete(SourceReferenceMentionRow).where(
                    SourceReferenceMentionRow.source_document_id == document_id
                )
            )
            await session.execute(
                delete(SourceReferenceEntryRow).where(
                    SourceReferenceEntryRow.source_document_id == document_id
                )
            )
            session.add_all(_reference_entry_row(item) for item in references.entries)
            await session.flush()
            session.add_all(_reference_mention_row(item) for item in references.mentions)
            session.add_all(
                _reference_resolution_row(item) for item in references.resolutions
            )
            session.add_all(_reference_candidate_row(item) for item in references.candidates)

    async def read_collection_references(
        self,
        collection_id: str,
    ) -> SourceReferenceSet:
        async with self.session_factory() as session:
            document_ids = select(SourceDocumentRow.source_document_id).where(
                SourceDocumentRow.collection_id == collection_id
            )
            entries = tuple(
                await session.scalars(
                    select(SourceReferenceEntryRow)
                    .where(SourceReferenceEntryRow.source_document_id.in_(document_ids))
                    .order_by(
                        SourceReferenceEntryRow.source_document_id,
                        SourceReferenceEntryRow.reference_index.asc().nulls_first(),
                        SourceReferenceEntryRow.reference_id,
                    )
                )
            )
            mentions = tuple(
                await session.scalars(
                    select(SourceReferenceMentionRow)
                    .where(SourceReferenceMentionRow.source_document_id.in_(document_ids))
                    .order_by(
                        SourceReferenceMentionRow.source_document_id,
                        SourceReferenceMentionRow.source_block_id.asc().nulls_first(),
                        SourceReferenceMentionRow.mention_id,
                    )
                )
            )
            reference_ids = tuple(item.reference_id for item in entries)
            resolutions = await self._references_by_ids(
                session, SourceReferenceResolutionRow, reference_ids
            )
            candidates = await self._references_by_ids(
                session, SourceReferenceCandidateRow, reference_ids
            )
        return SourceReferenceSet(
            entries=tuple(_entry_from_row(item) for item in entries),
            mentions=tuple(_mention_from_row(item) for item in mentions),
            resolutions=tuple(_resolution_from_row(item) for item in resolutions),
            candidates=tuple(_candidate_from_row(item) for item in candidates),
        )

    @staticmethod
    async def _references_by_ids(session, model, reference_ids):
        if not reference_ids:
            return ()
        statement = select(model).where(model.reference_id.in_(reference_ids))
        if model is SourceReferenceCandidateRow:
            statement = statement.order_by(model.relevance_score.desc(), model.candidate_id)
        else:
            statement = statement.order_by(
                model.reference_id, model.provider, model.resolution_id
            )
        return tuple(await session.scalars(statement))

    @staticmethod
    def _source_statement(model, collection_id: str):
        return (
            select(model)
            .join(
                SourceDocumentRow,
                SourceDocumentRow.source_document_id == model.source_document_id,
            )
            .where(SourceDocumentRow.collection_id == collection_id)
        )

    @staticmethod
    async def _text_units_by_block(
        session: AsyncSession,
        collection_id: str,
        document_id: str | None,
    ) -> dict[tuple[str, str], tuple[str, ...]]:
        statement = (
            select(
                SourceBlockTextUnit.source_document_id,
                SourceBlockTextUnit.block_id,
                SourceBlockTextUnit.text_unit_id,
            )
            .join(
                SourceDocumentRow,
                SourceDocumentRow.source_document_id
                == SourceBlockTextUnit.source_document_id,
            )
            .join(
                SourceTextUnitRow,
                (SourceTextUnitRow.source_document_id
                 == SourceBlockTextUnit.source_document_id)
                & (SourceTextUnitRow.text_unit_id
                   == SourceBlockTextUnit.text_unit_id),
            )
            .where(SourceDocumentRow.collection_id == collection_id)
        )
        if document_id is not None:
            statement = statement.where(
                SourceBlockTextUnit.source_document_id == document_id
            )
        rows = await session.execute(
            statement.order_by(
                SourceBlockTextUnit.source_document_id,
                SourceBlockTextUnit.block_id,
                SourceTextUnitRow.text_unit_order,
            )
        )
        grouped: dict[tuple[str, str], list[str]] = {}
        for source_document_id, block_id, text_unit_id in rows:
            grouped.setdefault((str(source_document_id), str(block_id)), []).append(
                str(text_unit_id)
            )
        return {key: tuple(values) for key, values in grouped.items()}

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
            item.reference_id is not None and item.reference_id not in reference_ids
            for item in references.mentions
        ):
            raise ValueError("Reference mentions must resolve within their document")
        if any(item.reference_id not in reference_ids for item in references.resolutions):
            raise ValueError("Reference resolutions must resolve within their document")
        if any(item.reference_id not in reference_ids for item in references.candidates):
            raise ValueError("Reference candidates must resolve within their document")


def _reference_entry_row(item: SourceReferenceEntry) -> SourceReferenceEntryRow:
    return SourceReferenceEntryRow(
        source_document_id=item.document_id,
        reference_id=item.reference_id,
        raw_reference=item.raw_reference,
        reference_index=item.reference_index,
        title=item.title,
        authors_text=item.authors_text,
        year=item.year,
        doi=item.doi,
        source_block_id=item.source_block_id,
        page=item.page,
        confidence=item.confidence,
        metadata_json=dict(item.metadata),
    )


def _reference_mention_row(item: SourceReferenceMention) -> SourceReferenceMentionRow:
    return SourceReferenceMentionRow(
        source_document_id=item.document_id,
        mention_id=item.mention_id,
        reference_id=item.reference_id,
        citation_marker=item.citation_marker,
        context_text=item.context_text,
        source_block_id=item.source_block_id,
        page=item.page,
        confidence=item.confidence,
        metadata_json=dict(item.metadata),
    )


def _reference_resolution_row(
    item: SourceReferenceResolution,
) -> SourceReferenceResolutionRow:
    return SourceReferenceResolutionRow(
        resolution_id=item.resolution_id,
        reference_id=item.reference_id,
        provider=item.provider,
        status=item.status,
        resolved_title=item.resolved_title,
        resolved_authors_text=item.resolved_authors_text,
        resolved_year=item.resolved_year,
        resolved_venue=item.resolved_venue,
        resolved_doi=item.resolved_doi,
        resolved_url=item.resolved_url,
        open_access_url=item.open_access_url,
        confidence=item.confidence,
        metadata_json=dict(item.metadata),
    )


def _reference_candidate_row(
    item: SourceReferenceCandidate,
) -> SourceReferenceCandidateRow:
    return SourceReferenceCandidateRow(
        candidate_id=item.candidate_id,
        reference_id=item.reference_id,
        status=item.status,
        relevance_score=item.relevance_score,
        relevance_reason=item.relevance_reason,
        cited_by_document_id=item.cited_by_document_id,
        mention_count=item.mention_count,
        representative_context=item.representative_context,
        resolved_doi=item.resolved_doi,
        resolved_url=item.resolved_url,
        open_access_url=item.open_access_url,
        metadata_json=dict(item.metadata),
    )


def _entry_from_row(row: SourceReferenceEntryRow) -> SourceReferenceEntry:
    return SourceReferenceEntry.from_record(
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


def _mention_from_row(row: SourceReferenceMentionRow) -> SourceReferenceMention:
    return SourceReferenceMention.from_record(
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


def _resolution_from_row(row: SourceReferenceResolutionRow) -> SourceReferenceResolution:
    return SourceReferenceResolution.from_record(
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


def _candidate_from_row(row: SourceReferenceCandidateRow) -> SourceReferenceCandidate:
    return SourceReferenceCandidate.from_record(
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


__all__ = ["PostgresSourceArtifactRepository"]
