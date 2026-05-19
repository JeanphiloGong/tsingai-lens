from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any

from config import DATA_DIR
from domain.source import (
    SourceArtifactSet,
    SourceBlock,
    SourceDocument,
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
)


class SqliteSourceArtifactRepository:
    """SQLite-backed persistence for Source document-structure artifacts."""

    backend_name = "sqlite"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or (DATA_DIR / "lens.sqlite")).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def replace_collection_artifacts(
        self,
        collection_id: str,
        artifacts: SourceArtifactSet,
    ) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            self._delete_collection_artifacts(connection, collection_id)
            self._insert_documents(connection, collection_id, artifacts.documents)
            self._insert_text_units(connection, collection_id, artifacts.text_units)
            self._insert_text_unit_documents(connection, collection_id, artifacts)
            self._insert_blocks(connection, collection_id, artifacts.blocks)
            self._insert_block_text_units(connection, collection_id, artifacts.blocks)
            self._insert_tables(connection, collection_id, artifacts.tables)
            self._insert_table_rows(connection, collection_id, artifacts.table_rows)
            self._insert_table_cells(connection, collection_id, artifacts.table_cells)
            self._insert_figures(connection, collection_id, artifacts.figures)
            connection.execute(
                """
                INSERT INTO source_artifact_builds (
                    collection_id,
                    schema_version,
                    artifact_version,
                    updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (collection_id, 1, "source-artifacts-v1", _now_iso()),
            )

    def read_collection_artifacts(self, collection_id: str) -> SourceArtifactSet:
        return SourceArtifactSet(
            documents=tuple(self.list_documents(collection_id)),
            text_units=tuple(self.list_text_units(collection_id)),
            blocks=tuple(self.list_blocks(collection_id)),
            tables=tuple(self.list_tables(collection_id)),
            table_rows=tuple(self.list_table_rows(collection_id)),
            table_cells=tuple(self.list_table_cells(collection_id)),
            figures=tuple(self.list_figures(collection_id)),
        )

    def replace_collection_references(
        self,
        collection_id: str,
        references: SourceReferenceSet,
    ) -> None:
        self._ensure_schema()
        with self._connection() as connection:
            self._delete_collection_references(connection, collection_id)
            self._insert_reference_entries(connection, collection_id, references.entries)
            self._insert_reference_mentions(
                connection,
                collection_id,
                references.mentions,
            )
            self._insert_reference_resolutions(
                connection,
                collection_id,
                references.resolutions,
            )
            self._insert_reference_candidates(
                connection,
                collection_id,
                references.candidates,
            )

    def read_collection_references(self, collection_id: str) -> SourceReferenceSet:
        self._ensure_schema()
        with self._connection() as connection:
            return SourceReferenceSet(
                entries=tuple(self._list_reference_entries(connection, collection_id)),
                mentions=tuple(self._list_reference_mentions(connection, collection_id)),
                resolutions=tuple(
                    self._list_reference_resolutions(connection, collection_id)
                ),
                candidates=tuple(
                    self._list_reference_candidates(connection, collection_id)
                ),
            )

    def list_documents(self, collection_id: str) -> list[SourceDocument]:
        self._ensure_schema()
        with self._connection() as connection:
            text_unit_ids_by_document = self._text_unit_ids_by_document(
                connection,
                collection_id,
            )
            rows = connection.execute(
                """
                SELECT
                    document_id,
                    human_readable_id,
                    title,
                    text,
                    creation_date,
                    metadata_json
                FROM source_documents
                WHERE collection_id = ?
                ORDER BY human_readable_id ASC, document_id ASC
                """,
                (collection_id,),
            ).fetchall()
        return [
            SourceDocument.from_record(
                {
                    "document_id": row["document_id"],
                    "human_readable_id": row["human_readable_id"],
                    "title": row["title"],
                    "text": row["text"],
                    "text_unit_ids": text_unit_ids_by_document.get(
                        row["document_id"],
                        [],
                    ),
                    "creation_date": row["creation_date"],
                    "metadata": _load_json_object(row["metadata_json"]),
                }
            )
            for row in rows
        ]

    def list_text_units(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceTextUnit]:
        self._ensure_schema()
        with self._connection() as connection:
            document_ids_by_text_unit = self._document_ids_by_text_unit(
                connection,
                collection_id,
            )
            if document_id is None:
                rows = connection.execute(
                    """
                    SELECT
                        text_unit_id,
                        human_readable_id,
                        text,
                        n_tokens
                    FROM source_text_units
                    WHERE collection_id = ?
                    ORDER BY human_readable_id ASC, text_unit_id ASC
                    """,
                    (collection_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT
                        tu.text_unit_id,
                        tu.human_readable_id,
                        tu.text,
                        tu.n_tokens
                    FROM source_text_units tu
                    JOIN source_text_unit_documents link
                      ON link.collection_id = tu.collection_id
                     AND link.text_unit_id = tu.text_unit_id
                    WHERE tu.collection_id = ?
                      AND link.document_id = ?
                    ORDER BY tu.human_readable_id ASC, tu.text_unit_id ASC
                    """,
                    (collection_id, document_id),
                ).fetchall()
        return [
            SourceTextUnit.from_record(
                {
                    "text_unit_id": row["text_unit_id"],
                    "human_readable_id": row["human_readable_id"],
                    "text": row["text"],
                    "n_tokens": row["n_tokens"],
                    "document_ids": document_ids_by_text_unit.get(
                        row["text_unit_id"],
                        [],
                    ),
                }
            )
            for row in rows
        ]

    def list_blocks(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceBlock]:
        self._ensure_schema()
        with self._connection() as connection:
            text_unit_ids_by_block = self._text_unit_ids_by_block(
                connection,
                collection_id,
            )
            rows = connection.execute(
                """
                SELECT
                    block_id,
                    document_id,
                    block_type,
                    text,
                    block_order,
                    page,
                    bbox_json,
                    char_range_json,
                    heading_path,
                    heading_level
                FROM source_blocks
                WHERE collection_id = ?
                  AND (? IS NULL OR document_id = ?)
                ORDER BY document_id ASC, block_order ASC, block_id ASC
                """,
                (collection_id, document_id, document_id),
            ).fetchall()
        return [
            SourceBlock.from_record(
                {
                    "block_id": row["block_id"],
                    "document_id": row["document_id"],
                    "block_type": row["block_type"],
                    "text": row["text"],
                    "block_order": row["block_order"],
                    "text_unit_ids": text_unit_ids_by_block.get(row["block_id"], []),
                    "page": row["page"],
                    "bbox": _load_json_object_or_none(row["bbox_json"]),
                    "char_range": _load_json_object_or_none(row["char_range_json"]),
                    "heading_path": row["heading_path"],
                    "heading_level": row["heading_level"],
                }
            )
            for row in rows
        ]

    def list_tables(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceTable]:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    table_id,
                    document_id,
                    table_order,
                    caption_text,
                    caption_block_id,
                    page,
                    bbox_json,
                    heading_path,
                    column_headers_json,
                    table_matrix_json,
                    metadata_json
                FROM source_tables
                WHERE collection_id = ?
                  AND (? IS NULL OR document_id = ?)
                ORDER BY document_id ASC, table_order ASC, table_id ASC
                """,
                (collection_id, document_id, document_id),
            ).fetchall()
        return [
            SourceTable.from_record(
                {
                    "table_id": row["table_id"],
                    "document_id": row["document_id"],
                    "table_order": row["table_order"],
                    "caption_text": row["caption_text"],
                    "caption_block_id": row["caption_block_id"],
                    "page": row["page"],
                    "bbox": _load_json_object_or_none(row["bbox_json"]),
                    "heading_path": row["heading_path"],
                    "column_headers": _load_json_list(row["column_headers_json"]),
                    "table_matrix": _load_json_list(row["table_matrix_json"]),
                    "metadata": _load_json_object(row["metadata_json"]),
                }
            )
            for row in rows
        ]

    def list_table_rows(
        self,
        collection_id: str,
        table_id: str | None = None,
    ) -> list[SourceTableRow]:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    row_id,
                    document_id,
                    table_id,
                    row_index,
                    row_text,
                    page,
                    bbox_json,
                    heading_path
                FROM source_table_rows
                WHERE collection_id = ?
                  AND (? IS NULL OR table_id = ?)
                ORDER BY document_id ASC, table_id ASC, row_index ASC, row_id ASC
                """,
                (collection_id, table_id, table_id),
            ).fetchall()
        return [
            SourceTableRow.from_record(
                {
                    "row_id": row["row_id"],
                    "document_id": row["document_id"],
                    "table_id": row["table_id"],
                    "row_index": row["row_index"],
                    "row_text": row["row_text"],
                    "page": row["page"],
                    "bbox": _load_json_object_or_none(row["bbox_json"]),
                    "heading_path": row["heading_path"],
                }
            )
            for row in rows
        ]

    def list_table_cells(
        self,
        collection_id: str,
        table_id: str | None = None,
        row_index: int | None = None,
    ) -> list[SourceTableCell]:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    cell_id,
                    document_id,
                    table_id,
                    row_index,
                    col_index,
                    cell_text,
                    header_path,
                    page,
                    bbox_json,
                    char_range_json,
                    unit_hint
                FROM source_table_cells
                WHERE collection_id = ?
                  AND (? IS NULL OR table_id = ?)
                  AND (? IS NULL OR row_index = ?)
                ORDER BY document_id ASC, table_id ASC, row_index ASC, col_index ASC
                """,
                (collection_id, table_id, table_id, row_index, row_index),
            ).fetchall()
        return [
            SourceTableCell.from_record(
                {
                    "cell_id": row["cell_id"],
                    "document_id": row["document_id"],
                    "table_id": row["table_id"],
                    "row_index": row["row_index"],
                    "col_index": row["col_index"],
                    "cell_text": row["cell_text"],
                    "header_path": row["header_path"],
                    "page": row["page"],
                    "bbox": _load_json_object_or_none(row["bbox_json"]),
                    "char_range": _load_json_object_or_none(row["char_range_json"]),
                    "unit_hint": row["unit_hint"],
                }
            )
            for row in rows
        ]

    def list_figures(
        self,
        collection_id: str,
        document_id: str | None = None,
    ) -> list[SourceFigure]:
        self._ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    figure_id,
                    document_id,
                    figure_order,
                    figure_label,
                    caption_text,
                    caption_block_id,
                    page,
                    bbox_json,
                    heading_path,
                    image_path,
                    image_mime_type,
                    image_width,
                    image_height,
                    asset_sha256,
                    metadata_json
                FROM source_figures
                WHERE collection_id = ?
                  AND (? IS NULL OR document_id = ?)
                ORDER BY document_id ASC, figure_order ASC, figure_id ASC
                """,
                (collection_id, document_id, document_id),
            ).fetchall()
        return [
            SourceFigure.from_record(
                {
                    "figure_id": row["figure_id"],
                    "document_id": row["document_id"],
                    "figure_order": row["figure_order"],
                    "figure_label": row["figure_label"],
                    "caption_text": row["caption_text"],
                    "caption_block_id": row["caption_block_id"],
                    "page": row["page"],
                    "bbox": _load_json_object_or_none(row["bbox_json"]),
                    "heading_path": row["heading_path"],
                    "image_path": row["image_path"],
                    "image_mime_type": row["image_mime_type"],
                    "image_width": row["image_width"],
                    "image_height": row["image_height"],
                    "asset_sha256": row["asset_sha256"],
                    "metadata": _load_json_object(row["metadata_json"]),
                }
            )
            for row in rows
        ]

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_documents (
                    collection_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    human_readable_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    creation_date TEXT,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (collection_id, document_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_text_units (
                    collection_id TEXT NOT NULL,
                    text_unit_id TEXT NOT NULL,
                    human_readable_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    n_tokens INTEGER,
                    PRIMARY KEY (collection_id, text_unit_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_text_unit_documents (
                    collection_id TEXT NOT NULL,
                    text_unit_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    PRIMARY KEY (collection_id, text_unit_id, document_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_blocks (
                    collection_id TEXT NOT NULL,
                    block_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    block_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    block_order INTEGER NOT NULL,
                    page INTEGER,
                    bbox_json TEXT,
                    char_range_json TEXT,
                    heading_path TEXT,
                    heading_level INTEGER,
                    PRIMARY KEY (collection_id, block_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_block_text_units (
                    collection_id TEXT NOT NULL,
                    block_id TEXT NOT NULL,
                    text_unit_id TEXT NOT NULL,
                    PRIMARY KEY (collection_id, block_id, text_unit_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_tables (
                    collection_id TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    table_order INTEGER NOT NULL,
                    caption_text TEXT,
                    caption_block_id TEXT,
                    page INTEGER,
                    bbox_json TEXT,
                    heading_path TEXT,
                    row_count INTEGER NOT NULL,
                    col_count INTEGER NOT NULL,
                    column_headers_json TEXT NOT NULL,
                    table_matrix_json TEXT NOT NULL,
                    table_markdown TEXT,
                    table_text TEXT,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (collection_id, table_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_table_rows (
                    collection_id TEXT NOT NULL,
                    row_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    row_text TEXT NOT NULL,
                    page INTEGER,
                    bbox_json TEXT,
                    heading_path TEXT,
                    PRIMARY KEY (collection_id, row_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_table_cells (
                    collection_id TEXT NOT NULL,
                    cell_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    col_index INTEGER NOT NULL,
                    cell_text TEXT NOT NULL,
                    header_path TEXT,
                    page INTEGER,
                    bbox_json TEXT,
                    char_range_json TEXT,
                    unit_hint TEXT,
                    PRIMARY KEY (collection_id, cell_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_figures (
                    collection_id TEXT NOT NULL,
                    figure_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    figure_order INTEGER NOT NULL,
                    figure_label TEXT,
                    caption_text TEXT,
                    caption_block_id TEXT,
                    page INTEGER,
                    bbox_json TEXT,
                    heading_path TEXT,
                    image_path TEXT,
                    image_mime_type TEXT,
                    image_width INTEGER,
                    image_height INTEGER,
                    asset_sha256 TEXT,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (collection_id, figure_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_artifact_builds (
                    collection_id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    artifact_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_reference_entries (
                    collection_id TEXT NOT NULL,
                    reference_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    raw_reference TEXT NOT NULL,
                    reference_index TEXT,
                    title TEXT,
                    authors_text TEXT,
                    year INTEGER,
                    doi TEXT,
                    source_block_id TEXT,
                    page INTEGER,
                    confidence REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (collection_id, reference_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_reference_mentions (
                    collection_id TEXT NOT NULL,
                    mention_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    reference_id TEXT,
                    citation_marker TEXT NOT NULL,
                    context_text TEXT NOT NULL,
                    source_block_id TEXT,
                    page INTEGER,
                    char_start INTEGER,
                    char_end INTEGER,
                    confidence REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (collection_id, mention_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_reference_resolutions (
                    collection_id TEXT NOT NULL,
                    resolution_id TEXT NOT NULL,
                    reference_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resolved_title TEXT,
                    resolved_authors_text TEXT,
                    resolved_year INTEGER,
                    resolved_venue TEXT,
                    resolved_doi TEXT,
                    resolved_url TEXT,
                    open_access_url TEXT,
                    confidence REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (collection_id, resolution_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_reference_candidates (
                    collection_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    reference_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    relevance_score REAL NOT NULL,
                    relevance_reason TEXT,
                    cited_by_document_id TEXT,
                    mention_count INTEGER NOT NULL,
                    representative_context TEXT,
                    resolved_doi TEXT,
                    resolved_url TEXT,
                    open_access_url TEXT,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (collection_id, candidate_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_source_blocks_doc_order
                ON source_blocks(collection_id, document_id, block_order)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_source_tables_doc_order
                ON source_tables(collection_id, document_id, table_order)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_source_rows_table
                ON source_table_rows(collection_id, table_id, row_index)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_source_cells_table_row
                ON source_table_cells(collection_id, table_id, row_index, col_index)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_source_figures_doc_order
                ON source_figures(collection_id, document_id, figure_order)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_source_reference_entries_doc
                ON source_reference_entries(collection_id, document_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_source_reference_mentions_doc_ref
                ON source_reference_mentions(collection_id, document_id, reference_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_source_reference_candidates_status
                ON source_reference_candidates(
                    collection_id,
                    status,
                    relevance_score DESC
                )
                """
            )

    def _delete_collection_artifacts(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
    ) -> None:
        for table_name in (
            "source_artifact_builds",
            "source_figures",
            "source_table_cells",
            "source_table_rows",
            "source_tables",
            "source_block_text_units",
            "source_blocks",
            "source_text_unit_documents",
            "source_text_units",
            "source_documents",
        ):
            connection.execute(
                f"DELETE FROM {table_name} WHERE collection_id = ?",
                (collection_id,),
            )

    def _delete_collection_references(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
    ) -> None:
        for table_name in (
            "source_reference_candidates",
            "source_reference_resolutions",
            "source_reference_mentions",
            "source_reference_entries",
        ):
            connection.execute(
                f"DELETE FROM {table_name} WHERE collection_id = ?",
                (collection_id,),
            )

    def _insert_documents(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        documents: tuple[SourceDocument, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_documents (
                collection_id,
                document_id,
                human_readable_id,
                title,
                text,
                creation_date,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id,
                    document.document_id,
                    document.human_readable_id,
                    document.title,
                    document.text,
                    document.creation_date,
                    _dump_json_object(document.metadata),
                )
                for document in documents
            ],
        )

    def _insert_text_units(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        text_units: tuple[SourceTextUnit, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_text_units (
                collection_id,
                text_unit_id,
                human_readable_id,
                text,
                n_tokens
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id,
                    text_unit.text_unit_id,
                    text_unit.human_readable_id,
                    text_unit.text,
                    text_unit.n_tokens,
                )
                for text_unit in text_units
            ],
        )

    def _insert_text_unit_documents(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        artifacts: SourceArtifactSet,
    ) -> None:
        links = {
            (text_unit.text_unit_id, document_id)
            for text_unit in artifacts.text_units
            for document_id in text_unit.document_ids
        }
        links.update(
            (text_unit_id, document.document_id)
            for document in artifacts.documents
            for text_unit_id in document.text_unit_ids
        )
        connection.executemany(
            """
            INSERT INTO source_text_unit_documents (
                collection_id,
                text_unit_id,
                document_id
            ) VALUES (?, ?, ?)
            """,
            [
                (collection_id, text_unit_id, document_id)
                for text_unit_id, document_id in sorted(links)
            ],
        )

    def _insert_blocks(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        blocks: tuple[SourceBlock, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_blocks (
                collection_id,
                block_id,
                document_id,
                block_type,
                text,
                block_order,
                page,
                bbox_json,
                char_range_json,
                heading_path,
                heading_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id,
                    block.block_id,
                    block.document_id,
                    str(block.block_type),
                    block.text,
                    block.block_order,
                    block.page,
                    block.bbox.to_json() if block.bbox else None,
                    block.char_range.to_json() if block.char_range else None,
                    block.heading_path,
                    block.heading_level,
                )
                for block in blocks
            ],
        )

    def _insert_block_text_units(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        blocks: tuple[SourceBlock, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_block_text_units (
                collection_id,
                block_id,
                text_unit_id
            ) VALUES (?, ?, ?)
            """,
            [
                (collection_id, block.block_id, text_unit_id)
                for block in blocks
                for text_unit_id in block.text_unit_ids
            ],
        )

    def _insert_tables(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        tables: tuple[SourceTable, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_tables (
                collection_id,
                table_id,
                document_id,
                table_order,
                caption_text,
                caption_block_id,
                page,
                bbox_json,
                heading_path,
                row_count,
                col_count,
                column_headers_json,
                table_matrix_json,
                table_markdown,
                table_text,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [self._table_values(collection_id, table) for table in tables],
        )

    def _insert_table_rows(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        rows: tuple[SourceTableRow, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_table_rows (
                collection_id,
                row_id,
                document_id,
                table_id,
                row_index,
                row_text,
                page,
                bbox_json,
                heading_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id,
                    row.row_id,
                    row.document_id,
                    row.table_id,
                    row.row_index,
                    row.row_text,
                    row.page,
                    row.bbox.to_json() if row.bbox else None,
                    row.heading_path,
                )
                for row in rows
            ],
        )

    def _insert_table_cells(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        cells: tuple[SourceTableCell, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_table_cells (
                collection_id,
                cell_id,
                document_id,
                table_id,
                row_index,
                col_index,
                cell_text,
                header_path,
                page,
                bbox_json,
                char_range_json,
                unit_hint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id,
                    cell.cell_id,
                    cell.document_id,
                    cell.table_id,
                    cell.row_index,
                    cell.col_index,
                    cell.cell_text,
                    cell.header_path,
                    cell.page,
                    cell.bbox.to_json() if cell.bbox else None,
                    cell.char_range.to_json() if cell.char_range else None,
                    cell.unit_hint,
                )
                for cell in cells
            ],
        )

    def _insert_figures(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        figures: tuple[SourceFigure, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_figures (
                collection_id,
                figure_id,
                document_id,
                figure_order,
                figure_label,
                caption_text,
                caption_block_id,
                page,
                bbox_json,
                heading_path,
                image_path,
                image_mime_type,
                image_width,
                image_height,
                asset_sha256,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id,
                    figure.figure_id,
                    figure.document_id,
                    figure.figure_order,
                    figure.figure_label,
                    figure.caption_text,
                    figure.caption_block_id,
                    figure.page,
                    figure.bbox.to_json() if figure.bbox else None,
                    figure.heading_path,
                    figure.image_path,
                    figure.image_mime_type,
                    figure.image_width,
                    figure.image_height,
                    figure.asset_sha256,
                    _dump_json_object(figure.metadata),
                )
                for figure in figures
            ],
        )

    def _insert_reference_entries(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        entries: tuple[SourceReferenceEntry, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_reference_entries (
                collection_id,
                reference_id,
                document_id,
                raw_reference,
                reference_index,
                title,
                authors_text,
                year,
                doi,
                source_block_id,
                page,
                confidence,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id,
                    entry.reference_id,
                    entry.document_id,
                    entry.raw_reference,
                    entry.reference_index,
                    entry.title,
                    entry.authors_text,
                    entry.year,
                    entry.doi,
                    entry.source_block_id,
                    entry.page,
                    entry.confidence,
                    _dump_json_object(entry.metadata),
                )
                for entry in entries
            ],
        )

    def _insert_reference_mentions(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        mentions: tuple[SourceReferenceMention, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_reference_mentions (
                collection_id,
                mention_id,
                document_id,
                reference_id,
                citation_marker,
                context_text,
                source_block_id,
                page,
                char_start,
                char_end,
                confidence,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id,
                    mention.mention_id,
                    mention.document_id,
                    mention.reference_id,
                    mention.citation_marker,
                    mention.context_text,
                    mention.source_block_id,
                    mention.page,
                    mention.char_start,
                    mention.char_end,
                    mention.confidence,
                    _dump_json_object(mention.metadata),
                )
                for mention in mentions
            ],
        )

    def _insert_reference_resolutions(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        resolutions: tuple[SourceReferenceResolution, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_reference_resolutions (
                collection_id,
                resolution_id,
                reference_id,
                provider,
                status,
                resolved_title,
                resolved_authors_text,
                resolved_year,
                resolved_venue,
                resolved_doi,
                resolved_url,
                open_access_url,
                confidence,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id,
                    resolution.resolution_id,
                    resolution.reference_id,
                    resolution.provider,
                    resolution.status,
                    resolution.resolved_title,
                    resolution.resolved_authors_text,
                    resolution.resolved_year,
                    resolution.resolved_venue,
                    resolution.resolved_doi,
                    resolution.resolved_url,
                    resolution.open_access_url,
                    resolution.confidence,
                    _dump_json_object(resolution.metadata),
                )
                for resolution in resolutions
            ],
        )

    def _insert_reference_candidates(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
        candidates: tuple[SourceReferenceCandidate, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO source_reference_candidates (
                collection_id,
                candidate_id,
                reference_id,
                status,
                relevance_score,
                relevance_reason,
                cited_by_document_id,
                mention_count,
                representative_context,
                resolved_doi,
                resolved_url,
                open_access_url,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id,
                    candidate.candidate_id,
                    candidate.reference_id,
                    candidate.status,
                    candidate.relevance_score,
                    candidate.relevance_reason,
                    candidate.cited_by_document_id,
                    candidate.mention_count,
                    candidate.representative_context,
                    candidate.resolved_doi,
                    candidate.resolved_url,
                    candidate.open_access_url,
                    _dump_json_object(candidate.metadata),
                )
                for candidate in candidates
            ],
        )

    def _table_values(
        self,
        collection_id: str,
        table: SourceTable,
    ) -> tuple[Any, ...]:
        record = table.to_record()
        return (
            collection_id,
            table.table_id,
            table.document_id,
            table.table_order,
            table.caption_text,
            table.caption_block_id,
            table.page,
            table.bbox.to_json() if table.bbox else None,
            table.heading_path,
            table.row_count,
            table.col_count,
            _dump_json_list(record["column_headers"]),
            _dump_json_list(record["table_matrix"]),
            record["table_markdown"],
            record["table_text"],
            _dump_json_object(table.metadata),
        )

    def _text_unit_ids_by_document(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
    ) -> dict[str, list[str]]:
        rows = connection.execute(
            """
            SELECT document_id, text_unit_id
            FROM source_text_unit_documents
            WHERE collection_id = ?
            ORDER BY document_id ASC, text_unit_id ASC
            """,
            (collection_id,),
        ).fetchall()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(row["document_id"], []).append(row["text_unit_id"])
        return grouped

    def _document_ids_by_text_unit(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
    ) -> dict[str, list[str]]:
        rows = connection.execute(
            """
            SELECT text_unit_id, document_id
            FROM source_text_unit_documents
            WHERE collection_id = ?
            ORDER BY text_unit_id ASC, document_id ASC
            """,
            (collection_id,),
        ).fetchall()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(row["text_unit_id"], []).append(row["document_id"])
        return grouped

    def _text_unit_ids_by_block(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
    ) -> dict[str, list[str]]:
        rows = connection.execute(
            """
            SELECT block_id, text_unit_id
            FROM source_block_text_units
            WHERE collection_id = ?
            ORDER BY block_id ASC, text_unit_id ASC
            """,
            (collection_id,),
        ).fetchall()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(row["block_id"], []).append(row["text_unit_id"])
        return grouped

    def _list_reference_entries(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
    ) -> list[SourceReferenceEntry]:
        rows = connection.execute(
            """
            SELECT
                reference_id,
                document_id,
                raw_reference,
                reference_index,
                title,
                authors_text,
                year,
                doi,
                source_block_id,
                page,
                confidence,
                metadata_json
            FROM source_reference_entries
            WHERE collection_id = ?
            ORDER BY document_id ASC, reference_index ASC, reference_id ASC
            """,
            (collection_id,),
        ).fetchall()
        return [
            SourceReferenceEntry.from_record(
                {
                    "reference_id": row["reference_id"],
                    "document_id": row["document_id"],
                    "raw_reference": row["raw_reference"],
                    "reference_index": row["reference_index"],
                    "title": row["title"],
                    "authors_text": row["authors_text"],
                    "year": row["year"],
                    "doi": row["doi"],
                    "source_block_id": row["source_block_id"],
                    "page": row["page"],
                    "confidence": row["confidence"],
                    "metadata": _load_json_object(row["metadata_json"]),
                }
            )
            for row in rows
        ]

    def _list_reference_mentions(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
    ) -> list[SourceReferenceMention]:
        rows = connection.execute(
            """
            SELECT
                mention_id,
                document_id,
                reference_id,
                citation_marker,
                context_text,
                source_block_id,
                page,
                char_start,
                char_end,
                confidence,
                metadata_json
            FROM source_reference_mentions
            WHERE collection_id = ?
            ORDER BY document_id ASC, source_block_id ASC, char_start ASC, mention_id ASC
            """,
            (collection_id,),
        ).fetchall()
        return [
            SourceReferenceMention.from_record(
                {
                    "mention_id": row["mention_id"],
                    "document_id": row["document_id"],
                    "reference_id": row["reference_id"],
                    "citation_marker": row["citation_marker"],
                    "context_text": row["context_text"],
                    "source_block_id": row["source_block_id"],
                    "page": row["page"],
                    "char_start": row["char_start"],
                    "char_end": row["char_end"],
                    "confidence": row["confidence"],
                    "metadata": _load_json_object(row["metadata_json"]),
                }
            )
            for row in rows
        ]

    def _list_reference_resolutions(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
    ) -> list[SourceReferenceResolution]:
        rows = connection.execute(
            """
            SELECT
                resolution_id,
                reference_id,
                provider,
                status,
                resolved_title,
                resolved_authors_text,
                resolved_year,
                resolved_venue,
                resolved_doi,
                resolved_url,
                open_access_url,
                confidence,
                metadata_json
            FROM source_reference_resolutions
            WHERE collection_id = ?
            ORDER BY reference_id ASC, provider ASC, resolution_id ASC
            """,
            (collection_id,),
        ).fetchall()
        return [
            SourceReferenceResolution.from_record(
                {
                    "resolution_id": row["resolution_id"],
                    "reference_id": row["reference_id"],
                    "provider": row["provider"],
                    "status": row["status"],
                    "resolved_title": row["resolved_title"],
                    "resolved_authors_text": row["resolved_authors_text"],
                    "resolved_year": row["resolved_year"],
                    "resolved_venue": row["resolved_venue"],
                    "resolved_doi": row["resolved_doi"],
                    "resolved_url": row["resolved_url"],
                    "open_access_url": row["open_access_url"],
                    "confidence": row["confidence"],
                    "metadata": _load_json_object(row["metadata_json"]),
                }
            )
            for row in rows
        ]

    def _list_reference_candidates(
        self,
        connection: sqlite3.Connection,
        collection_id: str,
    ) -> list[SourceReferenceCandidate]:
        rows = connection.execute(
            """
            SELECT
                candidate_id,
                reference_id,
                status,
                relevance_score,
                relevance_reason,
                cited_by_document_id,
                mention_count,
                representative_context,
                resolved_doi,
                resolved_url,
                open_access_url,
                metadata_json
            FROM source_reference_candidates
            WHERE collection_id = ?
            ORDER BY relevance_score DESC, candidate_id ASC
            """,
            (collection_id,),
        ).fetchall()
        return [
            SourceReferenceCandidate.from_record(
                {
                    "candidate_id": row["candidate_id"],
                    "reference_id": row["reference_id"],
                    "status": row["status"],
                    "relevance_score": row["relevance_score"],
                    "relevance_reason": row["relevance_reason"],
                    "cited_by_document_id": row["cited_by_document_id"],
                    "mention_count": row["mention_count"],
                    "representative_context": row["representative_context"],
                    "resolved_doi": row["resolved_doi"],
                    "resolved_url": row["resolved_url"],
                    "open_access_url": row["open_access_url"],
                    "metadata": _load_json_object(row["metadata_json"]),
                }
            )
            for row in rows
        ]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump_json_object(value: Any) -> str:
    return json.dumps(dict(value or {}), ensure_ascii=True, sort_keys=True)


def _dump_json_list(value: Any) -> str:
    return json.dumps(list(value or []), ensure_ascii=True)


def _load_json_object(value: Any) -> dict[str, Any]:
    parsed = _load_json(value, {})
    return dict(parsed) if isinstance(parsed, dict) else {}


def _load_json_object_or_none(value: Any) -> dict[str, Any] | None:
    parsed = _load_json(value, None)
    return dict(parsed) if isinstance(parsed, dict) else None


def _load_json_list(value: Any) -> list[Any]:
    parsed = _load_json(value, [])
    return list(parsed) if isinstance(parsed, list) else []


def _load_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default
