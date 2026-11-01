from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import (
    Any,
    Mapping,
)

import pandas as pd

from domain.source import (
    SourceBlock,
    SourceDocument,
    SourceFigure,
    SourceTable,
    SourceTableCell,
    SourceTableRow,
    SourceTextUnit,
    assemble_source_documents,
    render_markdown_table,
    render_plain_table_text,
)
from infra.source.mapping.values import normalize_optional_text, safe_int
from infra.source.mapping.values import _is_missing_value

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class SourceArtifactBundle:
    documents: pd.DataFrame
    text_units: pd.DataFrame
    blocks: pd.DataFrame
    figures: pd.DataFrame
    tables: pd.DataFrame
    table_rows: pd.DataFrame
    table_cells: pd.DataFrame
    figure_assets: dict[str, bytes]

    def to_documents(self) -> tuple[SourceDocument, ...]:
        documents = tuple(
            SourceDocument(
                document_id=item["id"],
                document_order=safe_int(item.get("document_order")) or 0,
                title=item.get("title") or "",
                text=item.get("text") or "",
                creation_date=normalize_optional_text(item.get("creation_date")),
                metadata=item.get("metadata") or {},
            )
            for item in _records(self.documents, "documents")
        )
        text_units = tuple(
            SourceTextUnit(
                text_unit_id=item["id"],
                text_unit_order=safe_int(item.get("text_unit_order")) or 0,
                text=item.get("text") or "",
                n_tokens=safe_int(item.get("n_tokens")),
                document_ids=tuple(item.get("document_ids") or ()),
            )
            for item in _records(self.text_units, "text_units")
        )
        blocks = tuple(
            SourceBlock(
                block_id=item["block_id"],
                document_id=item["document_id"],
                block_type=item["block_type"],
                text=item.get("text") or "",
                block_order=safe_int(item.get("block_order")) or 0,
                text_unit_ids=tuple(item.get("text_unit_ids") or ()),
                page=safe_int(item.get("page")),
                heading_path=normalize_optional_text(item.get("heading_path")),
                heading_level=safe_int(item.get("heading_level")),
            )
            for item in _records(self.blocks, "blocks")
        )
        tables = tuple(
            SourceTable(
                table_id=item["table_id"],
                document_id=item["document_id"],
                table_order=safe_int(item.get("table_order")) or 0,
                caption_text=normalize_optional_text(item.get("caption_text")),
                caption_block_id=normalize_optional_text(item.get("caption_block_id")),
                page=safe_int(item.get("page")),
                heading_path=normalize_optional_text(item.get("heading_path")),
                column_headers=tuple(item.get("column_headers") or ()),
                table_matrix=tuple(tuple(row) for row in item.get("table_matrix") or ()),
                header_row_count=(
                    header_count
                    if (header_count := safe_int(item.get("header_row_count"))) is not None
                    else 1
                ),
                metadata=item.get("metadata") or {},
            )
            for item in _records(self.tables, "tables")
        )
        table_rows = tuple(
            SourceTableRow(
                row_id=item["row_id"],
                document_id=item["document_id"],
                table_id=item["table_id"],
                row_index=safe_int(item.get("row_index")) or 0,
                row_text=item.get("row_text") or "",
                page=safe_int(item.get("page")),
                heading_path=normalize_optional_text(item.get("heading_path")),
            )
            for item in _records(self.table_rows, "table_rows")
        )
        table_cells = tuple(
            SourceTableCell(
                cell_id=item["cell_id"],
                document_id=item["id"],
                table_id=item["table_id"],
                row_index=safe_int(item.get("row_index")) or 0,
                col_index=safe_int(item.get("col_index")) or 0,
                cell_text=item.get("cell_text") or "",
                row_span=safe_int(item.get("row_span")) or 1,
                col_span=safe_int(item.get("col_span")) or 1,
                column_header=bool(item.get("column_header")),
                row_header=bool(item.get("row_header")),
                row_section=bool(item.get("row_section")),
                header_path=normalize_optional_text(item.get("header_path")),
                page=safe_int(item.get("page")),
                unit_hint=normalize_optional_text(item.get("unit_hint")),
            )
            for item in _records(self.table_cells, "table_cells")
        )
        figures = tuple(
            SourceFigure(
                figure_id=item["figure_id"],
                document_id=item["document_id"],
                figure_order=safe_int(item.get("figure_order")) or 0,
                figure_label=normalize_optional_text(item.get("figure_label")),
                caption_text=normalize_optional_text(item.get("caption_text")),
                caption_block_id=normalize_optional_text(item.get("caption_block_id")),
                page=safe_int(item.get("page")),
                heading_path=normalize_optional_text(item.get("heading_path")),
                image_path=normalize_optional_text(item.get("image_path")),
                image_mime_type=normalize_optional_text(item.get("image_mime_type")),
                image_width=safe_int(item.get("image_width")),
                image_height=safe_int(item.get("image_height")),
                asset_sha256=normalize_optional_text(item.get("asset_sha256")),
                image_size_bytes=safe_int(item.get("image_size_bytes")),
                metadata=item.get("metadata") or {},
            )
            for item in _records(self.figures, "figures")
        )
        return assemble_source_documents(
            documents=documents,
            text_units=text_units,
            blocks=blocks,
            tables=tables,
            table_rows=table_rows,
            table_cells=table_cells,
            figures=figures,
        )

def _records(frame: pd.DataFrame, artifact_kind: str) -> list[dict]:
    if frame is None or frame.empty:
        return []
    records = frame.to_dict(orient="records")
    sanitized_records: list[dict] = []
    for record in records:
        sanitized, removed_count = _remove_nul(record)
        sanitized_record = dict(sanitized)
        if artifact_kind == "blocks":
            raw_page = sanitized_record.get("page")
            try:
                page = float(raw_page) if raw_page is not None else 0.0
            except (TypeError, ValueError):
                page = 0.0
            sanitized_record["page"] = (
                int(page)
                if math.isfinite(page) and page > 0 and page.is_integer()
                else None
            )
        sanitized_records.append(sanitized_record)
        if removed_count:
            logger.warning(
                "Removed NUL characters from Source artifact "
                "artifact_kind=%s removed_count=%s",
                artifact_kind,
                removed_count,
            )
    return sanitized_records


def _remove_nul(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        count = value.count("\x00")
        return value.replace("\x00", ""), count
    if isinstance(value, Mapping):
        cleaned: dict[Any, Any] = {}
        removed_count = 0
        for key, item in value.items():
            cleaned_key, key_count = _remove_nul(key)
            cleaned_item, item_count = _remove_nul(item)
            cleaned[cleaned_key] = cleaned_item
            removed_count += key_count + item_count
        return cleaned, removed_count
    if isinstance(value, list):
        cleaned_items = []
        removed_count = 0
        for item in value:
            cleaned_item, item_count = _remove_nul(item)
            cleaned_items.append(cleaned_item)
            removed_count += item_count
        return cleaned_items, removed_count
    if isinstance(value, tuple):
        cleaned_items = []
        removed_count = 0
        for item in value:
            cleaned_item, item_count = _remove_nul(item)
            cleaned_items.append(cleaned_item)
            removed_count += item_count
        return tuple(cleaned_items), removed_count
    return value, 0


def source_document_payload(value: SourceDocument) -> dict[str, Any]:
    return {
        "id": value.document_id,
        "document_order": value.document_order,
        "title": value.title,
        "text": value.text,
        "text_unit_ids": list(value.text_unit_ids),
        "creation_date": value.creation_date,
        "metadata": dict(value.metadata),
    }


def source_text_unit_payload(value: SourceTextUnit) -> dict[str, Any]:
    return {
        "id": value.text_unit_id,
        "text_unit_order": value.text_unit_order,
        "text": value.text,
        "n_tokens": value.n_tokens,
        "document_ids": list(value.document_ids),
    }


def source_block_payload(value: SourceBlock) -> dict[str, Any]:
    return {
        "block_id": value.block_id,
        "document_id": value.document_id,
        "block_type": str(value.block_type),
        "text": value.text,
        "block_order": value.block_order,
        "text_unit_ids": list(value.text_unit_ids),
        "page": value.page,
        "heading_path": value.heading_path,
        "heading_level": value.heading_level,
    }


def source_table_payload(value: SourceTable) -> dict[str, Any]:
    matrix = [list(row) for row in value.table_matrix]
    headers = list(value.column_headers)
    return {
        "table_id": value.table_id,
        "document_id": value.document_id,
        "table_order": value.table_order,
        "caption_text": value.caption_text,
        "caption_block_id": value.caption_block_id,
        "page": value.page,
        "heading_path": value.heading_path,
        "row_count": value.row_count,
        "col_count": value.col_count,
        "header_row_count": value.header_row_count,
        "column_headers": headers,
        "table_matrix": matrix,
        "table_markdown": render_markdown_table(
            matrix,
            headers,
            header_row_count=value.header_row_count,
        ),
        "table_text": render_plain_table_text(matrix),
        "metadata": dict(value.metadata),
    }


def source_table_cell_payload(value: SourceTableCell) -> dict[str, Any]:
    return {
        "cell_id": value.cell_id,
        "document_id": value.document_id,
        "id": value.document_id,
        "table_id": value.table_id,
        "row_index": value.row_index,
        "col_index": value.col_index,
        "cell_text": value.cell_text,
        "row_span": value.row_span,
        "col_span": value.col_span,
        "column_header": value.column_header,
        "row_header": value.row_header,
        "row_section": value.row_section,
        "header_path": value.header_path,
        "page": value.page,
        "unit_hint": value.unit_hint,
    }


def source_table_row_payload(value: SourceTableRow) -> dict[str, Any]:
    return {
        "row_id": value.row_id,
        "document_id": value.document_id,
        "table_id": value.table_id,
        "row_index": value.row_index,
        "row_text": value.row_text,
        "page": value.page,
        "heading_path": value.heading_path,
    }


def source_figure_payload(value: SourceFigure) -> dict[str, Any]:
    return {
        "figure_id": value.figure_id,
        "document_id": value.document_id,
        "figure_order": value.figure_order,
        "figure_label": value.figure_label,
        "caption_text": value.caption_text,
        "caption_block_id": value.caption_block_id,
        "page": value.page,
        "heading_path": value.heading_path,
        "image_path": value.image_path,
        "image_mime_type": value.image_mime_type,
        "image_width": value.image_width,
        "image_height": value.image_height,
        "asset_sha256": value.asset_sha256,
        "image_size_bytes": value.image_size_bytes,
        "metadata": dict(value.metadata),
    }
