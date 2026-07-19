"""PostgreSQL persistence for versioned Source document structure."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from domain.source import (
    SourceArtifactSet,
    SourceBlock,
    SourceDocument,
    SourceDocumentTree,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
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
    SourceTable as SourceTableModel,
    SourceTableCell as SourceTableCellRow,
    SourceTableRow as SourceTableRowModel,
    SourceTextUnit as SourceTextUnitRow,
    SourceTextUnitDocument,
)


class PostgresSourceArtifactRepository:
    """Store immutable Source structure under an explicit collection build."""

    backend_name = "postgres"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def replace_collection_artifacts(
        self,
        collection_id: str,
        build_id: str,
        artifacts: SourceArtifactSet,
    ) -> None:
        with self.session_factory.begin() as session:
            build = self._require_build(session, collection_id, build_id)
            if build.status not in {"queued", "building"}:
                raise ValueError(f"collection build is not writable: {build_id}")
            lineage = self._resolve_document_lineage(
                session,
                collection_id,
                artifacts.documents,
            )
            session.execute(
                delete(SourceDocumentRow).where(SourceDocumentRow.build_id == build_id)
            )
            session.add_all(
                SourceDocumentRow(
                    build_id=build_id,
                    source_document_id=document.document_id,
                    collection_id=collection_id,
                    collection_document_id=lineage[document.document_id][0],
                    document_version_id=lineage[document.document_id][1],
                    human_readable_id=document.human_readable_id,
                    title=document.title,
                    text=document.text,
                    creation_date=document.creation_date,
                    metadata_json=dict(document.metadata),
                )
                for document in artifacts.documents
            )
            session.flush()
            session.add_all(
                SourceTextUnitRow(
                    build_id=build_id,
                    text_unit_id=text_unit.text_unit_id,
                    collection_id=collection_id,
                    human_readable_id=text_unit.human_readable_id,
                    text=text_unit.text,
                    n_tokens=text_unit.n_tokens,
                )
                for text_unit in artifacts.text_units
            )
            session.flush()
            session.add_all(
                SourceTextUnitDocument(
                    build_id=build_id,
                    text_unit_id=text_unit.text_unit_id,
                    source_document_id=document_id,
                    collection_id=collection_id,
                )
                for text_unit in artifacts.text_units
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
                    bbox_json=block.bbox.to_payload() if block.bbox else None,
                    char_range_json=(
                        {"start": block.char_range.start, "end": block.char_range.end}
                        if block.char_range
                        else None
                    ),
                    heading_path=block.heading_path,
                    heading_level=block.heading_level,
                )
                for block in artifacts.blocks
            )
            session.flush()
            session.add_all(
                SourceBlockTextUnit(
                    build_id=build_id,
                    block_id=block.block_id,
                    text_unit_id=text_unit_id,
                    collection_id=collection_id,
                )
                for block in artifacts.blocks
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
                    bbox_json=table.bbox.to_payload() if table.bbox else None,
                    heading_path=table.heading_path,
                    column_headers=list(table.column_headers),
                    table_matrix=[list(row) for row in table.table_matrix],
                    metadata_json=dict(table.metadata),
                )
                for table in artifacts.tables
            )
            session.flush()
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
                    bbox_json=row.bbox.to_payload() if row.bbox else None,
                    heading_path=row.heading_path,
                )
                for row in artifacts.table_rows
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
                    header_path=cell.header_path,
                    page=cell.page,
                    bbox_json=cell.bbox.to_payload() if cell.bbox else None,
                    char_range_json=(
                        {"start": cell.char_range.start, "end": cell.char_range.end}
                        if cell.char_range
                        else None
                    ),
                    unit_hint=cell.unit_hint,
                )
                for cell in artifacts.table_cells
            )

    def read_collection_artifacts(
        self,
        collection_id: str,
        build_id: str | None = None,
    ) -> SourceArtifactSet:
        return SourceArtifactSet(
            documents=tuple(self.list_documents(collection_id, build_id=build_id)),
            text_units=tuple(self.list_text_units(collection_id, build_id=build_id)),
            blocks=tuple(self.list_blocks(collection_id, build_id=build_id)),
            tables=tuple(self.list_tables(collection_id, build_id=build_id)),
            table_rows=tuple(self.list_table_rows(collection_id, build_id=build_id)),
            table_cells=tuple(self.list_table_cells(collection_id, build_id=build_id)),
        )

    def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
        build_id: str | None = None,
    ) -> SourceDocumentTree:
        document = next(
            (
                item
                for item in self.list_documents(collection_id, build_id=build_id)
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
            blocks=self.list_blocks(collection_id, document_id, build_id=build_id),
            tables=self.list_tables(collection_id, document_id, build_id=build_id),
        )

    def list_documents(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> list[SourceDocument]:
        with self.session_factory() as session:
            resolved_build_id = self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return []
            text_units_by_document = self._text_units_by_document(
                session, collection_id, resolved_build_id
            )
            rows = session.scalars(
                select(SourceDocumentRow)
                .where(
                    SourceDocumentRow.collection_id == collection_id,
                    SourceDocumentRow.build_id == resolved_build_id,
                )
                .order_by(
                    SourceDocumentRow.human_readable_id,
                    SourceDocumentRow.source_document_id,
                )
            )
            return [
                SourceDocument.from_record(
                    {
                        "document_id": row.source_document_id,
                        "human_readable_id": row.human_readable_id,
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

    def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTextUnit]:
        with self.session_factory() as session:
            resolved_build_id = self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return []
            documents_by_text_unit = self._documents_by_text_unit(
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
            rows = session.scalars(
                statement.order_by(
                    SourceTextUnitRow.human_readable_id,
                    SourceTextUnitRow.text_unit_id,
                )
            )
            return [
                SourceTextUnit.from_record(
                    {
                        "text_unit_id": row.text_unit_id,
                        "human_readable_id": row.human_readable_id,
                        "text": row.text,
                        "n_tokens": row.n_tokens,
                        "document_ids": documents_by_text_unit.get(
                            row.text_unit_id, ()
                        ),
                    }
                )
                for row in rows
            ]

    def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceBlock]:
        with self.session_factory() as session:
            resolved_build_id = self._resolve_read_build(
                session, collection_id, build_id
            )
            if resolved_build_id is None:
                return []
            text_units_by_block = self._text_units_by_block(
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
            rows = session.scalars(
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
                        "bbox": row.bbox_json,
                        "char_range": row.char_range_json,
                        "heading_path": row.heading_path,
                        "heading_level": row.heading_level,
                    }
                )
                for row in rows
            ]

    def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTable]:
        with self.session_factory() as session:
            resolved_build_id = self._resolve_read_build(
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
            rows = session.scalars(
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
                        "bbox": row.bbox_json,
                        "heading_path": row.heading_path,
                        "column_headers": row.column_headers,
                        "table_matrix": row.table_matrix,
                        "metadata": row.metadata_json,
                    }
                )
                for row in rows
            ]

    def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTableRow]:
        with self.session_factory() as session:
            resolved_build_id = self._resolve_read_build(
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
            rows = session.scalars(
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
                        "bbox": row.bbox_json,
                        "heading_path": row.heading_path,
                    }
                )
                for row in rows
            ]

    def list_table_cells(
        self,
        collection_id: str,
        table_id: str | None = None,
        row_index: int | None = None,
        *,
        build_id: str | None = None,
    ) -> list[SourceTableCell]:
        with self.session_factory() as session:
            resolved_build_id = self._resolve_read_build(
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
            rows = session.scalars(
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
                        "header_path": row.header_path,
                        "page": row.page,
                        "bbox": row.bbox_json,
                        "char_range": row.char_range_json,
                        "unit_hint": row.unit_hint,
                    }
                )
                for row in rows
            ]

    @staticmethod
    def _require_build(
        session: Session,
        collection_id: str,
        build_id: str,
    ) -> CollectionBuild:
        build = session.get(CollectionBuild, build_id)
        if build is None or build.collection_id != collection_id:
            raise FileNotFoundError(
                f"collection build not found: {collection_id}/{build_id}"
            )
        return build

    @staticmethod
    def _resolve_read_build(
        session: Session,
        collection_id: str,
        build_id: str | None,
    ) -> str | None:
        if build_id is not None:
            PostgresSourceArtifactRepository._require_build(
                session, collection_id, build_id
            )
            return build_id
        return session.scalar(
            select(CollectionActiveBuild.build_id).where(
                CollectionActiveBuild.collection_id == collection_id
            )
        )

    @staticmethod
    def _resolve_document_lineage(
        session: Session,
        collection_id: str,
        documents: tuple[SourceDocument, ...],
    ) -> dict[str, tuple[str, str]]:
        file_rows = session.execute(
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
                    "source document must resolve to exactly one collection file: "
                    f"{document.document_id}/{source_path}"
                )
            result[document.document_id] = unique_matches[0]
        return result

    @staticmethod
    def _documents_by_text_unit(
        session: Session, collection_id: str, build_id: str
    ) -> dict[str, tuple[str, ...]]:
        rows = session.execute(
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
    def _text_units_by_document(
        session: Session, collection_id: str, build_id: str
    ) -> dict[str, tuple[str, ...]]:
        rows = session.execute(
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
                SourceTextUnitRow.human_readable_id,
                SourceTextUnitDocument.text_unit_id,
            )
        )
        return _group_pairs(rows)

    @staticmethod
    def _text_units_by_block(
        session: Session, collection_id: str, build_id: str
    ) -> dict[str, tuple[str, ...]]:
        rows = session.execute(
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
                SourceTextUnitRow.human_readable_id,
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
