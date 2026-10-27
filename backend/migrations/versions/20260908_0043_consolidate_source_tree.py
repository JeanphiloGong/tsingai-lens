"""Consolidate current Source rows into one canonical tree artifact.

Revision ID: 20260908_0043
Revises: 20260907_0042
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import (
    Any,
    Mapping,
)

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from domain.source import (
    SourceBlock,
    SourceDocument,
    SourceFigure,
    SourceReferenceCandidate,
    SourceReferenceEntry,
    SourceReferenceMention,
    SourceReferenceResolution,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
    normalize_optional_text,
    safe_int,
)
from domain.source.artifacts import _is_missing_value

revision: str = "20260908_0043"
down_revision: str | Sequence[str] | None = "20260907_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "document_sources" not in existing:
        op.create_table(
            "document_sources",
            sa.Column("source_id", sa.String(length=128), nullable=False),
            sa.Column("document_id", sa.String(length=64), nullable=False),
            sa.Column("collection_id", sa.String(length=64), nullable=False),
            sa.Column("source_format", sa.String(length=32), nullable=False),
            sa.Column("parser_name", sa.String(length=128), nullable=False),
            sa.Column("parser_version", sa.String(length=128), nullable=False),
            sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("artifact_json", _JSON_DOCUMENT, nullable=False),
            sa.Column("tree_json", _JSON_DOCUMENT, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["document_id"], ["documents.document_id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["collection_id"], ["collections.collection_id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("source_id"),
            sa.UniqueConstraint("document_id", name="uq_document_sources_document_id"),
        )
        op.create_index(
            "ix_document_sources_document_id",
            "document_sources",
            ["document_id"],
            unique=False,
        )
        op.create_index(
            "ix_document_sources_collection_id",
            "document_sources",
            ["collection_id"],
            unique=False,
        )
    if "source_documents" in existing:
        _backfill(bind, existing)
        for table_name in (
            "source_block_text_units",
            "source_table_cells",
            "source_table_rows",
            "source_reference_mentions",
            "source_reference_candidates",
            "source_reference_resolutions",
            "source_reference_entries",
            "source_figures",
            "source_tables",
            "source_blocks",
            "source_text_units",
            "source_documents",
        ):
            if table_name in existing:
                op.drop_table(table_name)


def downgrade() -> None:
    raise RuntimeError(
        "20260908_0043 is an irreversible destructive cutover to canonical Source tree storage"
    )


def _backfill(bind: sa.Connection, existing: set[str]) -> None:
    metadata = sa.MetaData()
    metadata.reflect(bind=bind, only=tuple(existing))
    source_documents = metadata.tables["source_documents"]
    document_sources = sa.Table("document_sources", sa.MetaData(), autoload_with=bind)
    rows = bind.execute(sa.select(source_documents)).mappings()
    now = datetime.now(timezone.utc)
    for source_row in rows:
        document_id = str(source_row["source_document_id"])
        collection_id = str(source_row["collection_id"])
        artifact = _legacy_artifact(metadata, bind, source_row)
        references = _legacy_references(metadata, bind, document_id)
        artifact["references"] = references
        serialized = _canonical_json(artifact)
        metadata_json = dict(source_row.get("metadata_json") or {})
        parser_name = str(metadata_json.get("source_parser") or "legacy")
        parser_version = str(metadata_json.get("parser_version") or "legacy")
        source_format = str(
            metadata_json.get("source_format")
            or metadata_json.get("file_type")
            or "unknown"
        )
        tree = _legacy_tree(collection_id, artifact, references)
        bind.execute(
            document_sources.insert().values(
                source_id=f"src_{document_id}",
                document_id=document_id,
                collection_id=collection_id,
                source_format=source_format,
                parser_name=parser_name,
                parser_version=parser_version,
                source_fingerprint=hashlib.sha256(
                    serialized.encode("utf-8")
                ).hexdigest(),
                artifact_json=artifact,
                tree_json=tree,
                created_at=now,
                updated_at=now,
            )
        )


def _legacy_artifact(
    metadata: sa.MetaData,
    bind: sa.Connection,
    source_row: Any,
) -> dict[str, Any]:
    document_id = str(source_row["source_document_id"])
    def rows(table_name: str, **filters: Any) -> list[dict[str, Any]]:
        if table_name not in metadata.tables:
            return []
        table = metadata.tables[table_name]
        statement = sa.select(table)
        for column_name, value in filters.items():
            statement = statement.where(table.c[column_name] == value)
        return [dict(row) for row in bind.execute(statement).mappings()]

    text_units = [
        {
            "text_unit_id": row["text_unit_id"],
            "text_unit_order": row["text_unit_order"],
            "text": row["text"],
            "n_tokens": row["n_tokens"],
            "document_ids": [document_id],
        }
        for row in rows("source_text_units", source_document_id=document_id)
    ]
    block_links = rows("source_block_text_units", source_document_id=document_id)
    links_by_block: dict[str, list[str]] = {}
    for row in block_links:
        links_by_block.setdefault(str(row["block_id"]), []).append(
            str(row["text_unit_id"])
        )
    blocks = [
        {
            "block_id": row["block_id"],
            "document_id": document_id,
            "block_type": row["block_type"],
            "text": row["text"],
            "block_order": row["block_order"],
            "text_unit_ids": links_by_block.get(str(row["block_id"]), []),
            "page": row["page"],
            "heading_path": row["heading_path"],
            "heading_level": row["heading_level"],
        }
        for row in rows("source_blocks", source_document_id=document_id)
    ]
    tables = [
        {
            "table_id": row["table_id"],
            "document_id": document_id,
            "table_order": row["table_order"],
            "caption_text": row["caption_text"],
            "caption_block_id": row["caption_block_id"],
            "page": row["page"],
            "heading_path": row["heading_path"],
            "header_row_count": row["header_row_count"],
            "column_headers": row["column_headers"],
            "table_matrix": row["table_matrix"],
            "metadata": row["metadata_json"],
        }
        for row in rows("source_tables", source_document_id=document_id)
    ]
    table_rows = [
        {
            "row_id": row["row_id"],
            "document_id": document_id,
            "table_id": row["table_id"],
            "row_index": row["row_index"],
            "row_text": row["row_text"],
            "page": row["page"],
            "heading_path": row["heading_path"],
        }
        for row in rows("source_table_rows", source_document_id=document_id)
    ]
    table_cells = [
        {
            "cell_id": row["cell_id"],
            "document_id": document_id,
            "table_id": row["table_id"],
            "row_index": row["row_index"],
            "col_index": row["col_index"],
            "cell_text": row["cell_text"],
            "row_span": row["row_span"],
            "col_span": row["col_span"],
            "column_header": row["column_header"],
            "row_header": row["row_header"],
            "row_section": row["row_section"],
            "header_path": row["header_path"],
            "page": row["page"],
            "unit_hint": row["unit_hint"],
        }
        for row in rows("source_table_cells", source_document_id=document_id)
    ]
    figures = [
        {
            "figure_id": row["figure_id"],
            "document_id": document_id,
            "figure_order": row["figure_order"],
            "figure_label": row["figure_label"],
            "caption_text": row["caption_text"],
            "caption_block_id": row["caption_block_id"],
            "page": row["page"],
            "heading_path": row["heading_path"],
            "image_path": row["image_storage_key"],
            "image_mime_type": row["image_mime_type"],
            "image_width": row["image_width"],
            "image_height": row["image_height"],
            "asset_sha256": row["asset_sha256"],
            "image_size_bytes": row["image_size_bytes"],
            "metadata": row["metadata_json"],
        }
        for row in rows("source_figures", source_document_id=document_id)
    ]
    return {
        "document": {
            "document_id": document_id,
            "document_order": source_row["document_order"],
            "title": source_row["title"],
            "text": source_row["text"],
            "creation_date": source_row["creation_date"],
            "metadata": source_row["metadata_json"],
        },
        "text_units": text_units,
        "blocks": blocks,
        "tables": tables,
        "table_rows": table_rows,
        "table_cells": table_cells,
        "figures": figures,
    }


def _legacy_references(
    metadata: sa.MetaData,
    bind: sa.Connection,
    document_id: str,
) -> dict[str, list[dict[str, Any]]]:
    def rows(table_name: str, **filters: Any) -> list[dict[str, Any]]:
        if table_name not in metadata.tables:
            return []
        table = metadata.tables[table_name]
        statement = sa.select(table)
        for column_name, value in filters.items():
            statement = statement.where(table.c[column_name] == value)
        return [dict(row) for row in bind.execute(statement).mappings()]

    entries = rows("source_reference_entries", source_document_id=document_id)
    reference_ids = [str(row["reference_id"]) for row in entries]
    references = {
        "entries": [
            {
                "reference_id": row["reference_id"],
                "document_id": document_id,
                "raw_reference": row["raw_reference"],
                "reference_index": row["reference_index"],
                "title": row["title"],
                "authors_text": row["authors_text"],
                "year": row["year"],
                "doi": row["doi"],
                "source_block_id": row["source_block_id"],
                "page": row["page"],
                "confidence": row["confidence"],
                "metadata": row["metadata_json"],
            }
            for row in entries
        ],
        "mentions": [
            {
                "mention_id": row["mention_id"],
                "document_id": document_id,
                "reference_id": row["reference_id"],
                "citation_marker": row["citation_marker"],
                "context_text": row["context_text"],
                "source_block_id": row["source_block_id"],
                "page": row["page"],
                "confidence": row["confidence"],
                "metadata": row["metadata_json"],
            }
            for row in rows("source_reference_mentions", source_document_id=document_id)
        ],
        "resolutions": [],
        "candidates": [],
    }
    if reference_ids:
        references["resolutions"] = [
            {
                **{key: row[key] for key in (
                    "resolution_id",
                    "reference_id",
                    "provider",
                    "status",
                    "resolved_title",
                    "resolved_authors_text",
                    "resolved_year",
                    "resolved_venue",
                    "resolved_doi",
                    "resolved_url",
                    "open_access_url",
                    "confidence",
                )},
                "metadata": row["metadata_json"],
            }
            for row in rows("source_reference_resolutions")
            if str(row["reference_id"]) in reference_ids
        ]
        references["candidates"] = [
            {
                **{key: row[key] for key in (
                    "candidate_id",
                    "reference_id",
                    "status",
                    "relevance_score",
                    "relevance_reason",
                    "cited_by_document_id",
                    "mention_count",
                    "representative_context",
                    "resolved_doi",
                    "resolved_url",
                    "open_access_url",
                )},
                "metadata": row["metadata_json"],
            }
            for row in rows("source_reference_candidates")
            if str(row["reference_id"]) in reference_ids
        ]
    return references


def _legacy_tree(
    collection_id: str,
    artifact: dict[str, Any],
    references: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    from domain.source import (
        SourceDocument,
        SourceReferenceCandidate,
        SourceReferenceEntry,
        SourceReferenceMention,
        SourceReferenceResolution,
        SourceReferenceSet,
        build_source_document_tree,
    )

    document = dict(artifact["document"])
    document.update(
        {
            key: artifact[key]
            for key in (
                "text_units",
                "blocks",
                "tables",
                "table_rows",
                "table_cells",
                "figures",
            )
        }
    )
    source = SourceDocument(
        document_id=str(document.get("document_id") or document.get("id") or ""),
        document_order=safe_int(document.get("document_order")) or 0,
        title=str(document.get("title") or ""),
        text=str(document.get("text") or ""),
        creation_date=normalize_optional_text(document.get("creation_date")),
        metadata=_mapping(document.get("metadata")),
        text_units=tuple(
            (
                SourceTextUnit(
                    text_unit_id=str(item.get("text_unit_id") or item.get("id") or ""),
                    text_unit_order=safe_int(item.get("text_unit_order")) or 0,
                    text=str(item.get("text") or ""),
                    n_tokens=safe_int(item.get("n_tokens")),
                    document_ids=_string_tuple(item.get("document_ids")),
                )
                for item in document.get("text_units") or ()
                if isinstance(item, Mapping)
            )
        ),
        blocks=tuple(
            (
                SourceBlock(
                    block_id=str(item.get("block_id") or ""),
                    document_id=str(item.get("document_id") or item.get("id") or ""),
                    block_type=str(item.get("block_type") or "paragraph"),
                    text=str(item.get("text") or ""),
                    block_order=safe_int(item.get("block_order")) or 0,
                    text_unit_ids=_string_tuple(item.get("text_unit_ids")),
                    page=safe_int(item.get("page")),
                    heading_path=normalize_optional_text(item.get("heading_path")),
                    heading_level=safe_int(item.get("heading_level")),
                )
                for item in document.get("blocks") or ()
                if isinstance(item, Mapping)
            )
        ),
        tables=tuple(
            (
                SourceTable(
                    table_id=str(item.get("table_id") or ""),
                    document_id=str(item.get("document_id") or ""),
                    table_order=safe_int(item.get("table_order")) or 0,
                    caption_text=normalize_optional_text(item.get("caption_text")),
                    caption_block_id=normalize_optional_text(
                        item.get("caption_block_id")
                    ),
                    page=safe_int(item.get("page")),
                    heading_path=normalize_optional_text(item.get("heading_path")),
                    column_headers=_string_tuple(item.get("column_headers")),
                    table_matrix=_table_matrix_tuple(item.get("table_matrix")),
                    header_row_count=max(
                        0,
                        (
                            safe_int(item.get("header_row_count"))
                            if safe_int(item.get("header_row_count")) is not None
                            else 1
                        ),
                    ),
                    metadata=_mapping(item.get("metadata")),
                )
                for item in document.get("tables") or ()
                if isinstance(item, Mapping)
            )
        ),
        table_rows=tuple(
            (
                SourceTableRow(
                    row_id=str(item.get("row_id") or ""),
                    document_id=str(item.get("document_id") or ""),
                    table_id=str(item.get("table_id") or ""),
                    row_index=safe_int(item.get("row_index")) or 0,
                    row_text=str(item.get("row_text") or ""),
                    page=safe_int(item.get("page")),
                    heading_path=normalize_optional_text(item.get("heading_path")),
                )
                for item in document.get("table_rows") or ()
                if isinstance(item, Mapping)
            )
        ),
        table_cells=tuple(
            (
                SourceTableCell(
                    cell_id=str(item.get("cell_id") or ""),
                    document_id=str(item.get("document_id") or item.get("id") or ""),
                    table_id=str(item.get("table_id") or ""),
                    row_index=safe_int(item.get("row_index")) or 0,
                    col_index=safe_int(item.get("col_index")) or 0,
                    cell_text=str(item.get("cell_text") or ""),
                    row_span=max(
                        1,
                        (
                            safe_int(item.get("row_span"))
                            if safe_int(item.get("row_span")) is not None
                            else 1
                        ),
                    ),
                    col_span=max(
                        1,
                        (
                            safe_int(item.get("col_span"))
                            if safe_int(item.get("col_span")) is not None
                            else 1
                        ),
                    ),
                    column_header=bool(item.get("column_header")),
                    row_header=bool(item.get("row_header")),
                    row_section=bool(item.get("row_section")),
                    header_path=normalize_optional_text(item.get("header_path")),
                    page=safe_int(item.get("page")),
                    unit_hint=normalize_optional_text(item.get("unit_hint")),
                )
                for item in document.get("table_cells") or ()
                if isinstance(item, Mapping)
            )
        ),
        figures=tuple(
            (
                SourceFigure(
                    figure_id=str(item.get("figure_id") or ""),
                    document_id=str(item.get("document_id") or ""),
                    figure_order=safe_int(item.get("figure_order")) or 0,
                    figure_label=normalize_optional_text(item.get("figure_label")),
                    caption_text=normalize_optional_text(item.get("caption_text")),
                    caption_block_id=normalize_optional_text(
                        item.get("caption_block_id")
                    ),
                    page=safe_int(item.get("page")),
                    heading_path=normalize_optional_text(item.get("heading_path")),
                    image_path=normalize_optional_text(item.get("image_path")),
                    image_mime_type=normalize_optional_text(
                        item.get("image_mime_type")
                    ),
                    image_width=safe_int(item.get("image_width")),
                    image_height=safe_int(item.get("image_height")),
                    asset_sha256=normalize_optional_text(item.get("asset_sha256")),
                    image_size_bytes=safe_int(item.get("image_size_bytes")),
                    metadata=_mapping(item.get("metadata")),
                )
                for item in document.get("figures") or ()
                if isinstance(item, Mapping)
            )
        ),
    )
    source_references = SourceReferenceSet(
        entries=tuple(
            SourceReferenceEntry(
                reference_id=str(item.get("reference_id") or ""),
                document_id=str(item.get("document_id") or ""),
                raw_reference=str(item.get("raw_reference") or ""),
                reference_index=normalize_optional_text(item.get("reference_index")),
                title=normalize_optional_text(item.get("title")),
                authors_text=normalize_optional_text(item.get("authors_text")),
                year=safe_int(item.get("year")),
                doi=normalize_optional_text(item.get("doi")),
                source_block_id=normalize_optional_text(item.get("source_block_id")),
                page=safe_int(item.get("page")),
                confidence=float(item.get("confidence") or 0.0),
                metadata=_mapping(item.get("metadata")),
            )
            for item in references["entries"]
        ),
        mentions=tuple(
            SourceReferenceMention(
                mention_id=str(item.get("mention_id") or ""),
                document_id=str(item.get("document_id") or ""),
                reference_id=normalize_optional_text(item.get("reference_id")),
                citation_marker=str(item.get("citation_marker") or ""),
                context_text=str(item.get("context_text") or ""),
                source_block_id=normalize_optional_text(item.get("source_block_id")),
                page=safe_int(item.get("page")),
                confidence=float(item.get("confidence") or 0.0),
                metadata=_mapping(item.get("metadata")),
            )
            for item in references["mentions"]
        ),
        resolutions=tuple(
            SourceReferenceResolution(
                resolution_id=str(item.get("resolution_id") or ""),
                reference_id=str(item.get("reference_id") or ""),
                provider=str(item.get("provider") or ""),
                status=str(item.get("status") or "unresolved"),
                resolved_title=normalize_optional_text(item.get("resolved_title")),
                resolved_authors_text=normalize_optional_text(
                    item.get("resolved_authors_text")
                ),
                resolved_year=safe_int(item.get("resolved_year")),
                resolved_venue=normalize_optional_text(item.get("resolved_venue")),
                resolved_doi=normalize_optional_text(item.get("resolved_doi")),
                resolved_url=normalize_optional_text(item.get("resolved_url")),
                open_access_url=normalize_optional_text(item.get("open_access_url")),
                confidence=float(item.get("confidence") or 0.0),
                metadata=_mapping(item.get("metadata")),
            )
            for item in references["resolutions"]
        ),
        candidates=tuple(
            SourceReferenceCandidate(
                candidate_id=str(item.get("candidate_id") or ""),
                reference_id=str(item.get("reference_id") or ""),
                status=str(item.get("status") or "metadata_only"),
                relevance_score=float(item.get("relevance_score") or 0.0),
                relevance_reason=normalize_optional_text(item.get("relevance_reason")),
                cited_by_document_id=normalize_optional_text(
                    item.get("cited_by_document_id")
                ),
                mention_count=safe_int(item.get("mention_count")) or 0,
                representative_context=normalize_optional_text(
                    item.get("representative_context")
                ),
                resolved_doi=normalize_optional_text(item.get("resolved_doi")),
                resolved_url=normalize_optional_text(item.get("resolved_url")),
                open_access_url=normalize_optional_text(item.get("open_access_url")),
                metadata=_mapping(item.get("metadata")),
            )
            for item in references["candidates"]
        ),
    )
    tree = build_source_document_tree(
        collection_id=collection_id,
        document=source,
        blocks=source.blocks,
        tables=source.tables,
        figures=source.figures,
        references=source_references,
    )
    return {
        "document_id": tree.document_id,
        "collection_id": tree.collection_id,
        "root_node_id": tree.root_node_id,
        "nodes": {
            node_id: {
                "node_id": node.node_id,
                "document_id": node.document_id,
                "parent_id": node.parent_id,
                "child_ids": list(node.child_ids),
                "node_type": str(node.node_type),
                "semantic_role": node.semantic_role,
                "title": node.title,
                "text": node.text,
                "level": node.level,
                "order": node.order,
                "heading_path": list(node.heading_path),
                "source_ref_kind": node.source_ref_kind,
                "source_ref_id": node.source_ref_id,
                "page_start": node.page_start,
                "page_end": node.page_end,
                "text_unit_ids": list(node.text_unit_ids),
                "warnings": list(node.warnings),
            }
            for node_id, node in sorted(
                tree.nodes.items(), key=lambda item: item[1].order
            )
        },
        "reference_records": {
            reference_id: {
                "reference_id": reference.reference_id,
                "document_id": reference.document_id,
                "raw_reference": reference.raw_reference,
                "reference_index": reference.reference_index,
                "title": reference.title,
                "authors_text": reference.authors_text,
                "year": reference.year,
                "doi": reference.doi,
                "source_block_id": reference.source_block_id,
                "page": reference.page,
                "confidence": reference.confidence,
                "metadata": dict(reference.metadata),
            }
            for reference_id, reference in tree.reference_records.items()
        },
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _string_tuple(value: Any) -> tuple[str, ...]:
    if _is_missing_value(value):
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return (text,)
            return _string_tuple(parsed)
        return (text,)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        return tuple(str(item) for item in value if not _is_missing_value(item))
    return (str(value),)


def _table_matrix_tuple(value: Any) -> tuple[tuple[str, ...], ...]:
    if _is_missing_value(value):
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return ((text,),)
        return _table_matrix_tuple(parsed)
    if not isinstance(value, Iterable) or isinstance(value, (bytes, Mapping)):
        return ((str(value),),)

    rows = []
    for row in value:
        if isinstance(row, str) or not isinstance(row, Iterable):
            rows.append((str(row),))
        else:
            rows.append(tuple(str(cell) for cell in row))
    return tuple(rows)


def _mapping(value: Any) -> Mapping[str, Any]:
    if _is_missing_value(value):
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}
