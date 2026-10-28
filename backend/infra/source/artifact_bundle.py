from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from typing import (
    Any,
    Iterable,
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
    normalize_optional_text,
    render_markdown_table,
    render_plain_table_text,
    safe_int,
)
from domain.source.artifacts import _is_missing_value

logger = logging.getLogger(__name__)

_ARTIFACT_ID_FIELDS = (
    "cell_id",
    "row_id",
    "figure_id",
    "block_id",
    "table_id",
    "text_unit_id",
    "id",
    "document_id",
)


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
        return source_documents_from_records(
            documents=_records(self.documents, "documents"),
            text_units=_records(self.text_units, "text_units"),
            blocks=_records(self.blocks, "blocks"),
            figures=_records(self.figures, "figures"),
            tables=_records(self.tables, "tables"),
            table_rows=_records(self.table_rows, "table_rows"),
            table_cells=_records(self.table_cells, "table_cells"),
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
            artifact_id = next(
                (
                    str(sanitized_record[field])
                    for field in _ARTIFACT_ID_FIELDS
                    if sanitized_record.get(field) not in (None, "")
                ),
                "unknown",
            )
            logger.warning(
                "Removed NUL characters from Source artifact "
                "artifact_kind=%s artifact_id=%s removed_count=%s",
                artifact_kind,
                artifact_id,
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


def source_documents_from_records(
    *,
    documents: Iterable[Mapping[str, Any]] = (),
    text_units: Iterable[Mapping[str, Any]] = (),
    blocks: Iterable[Mapping[str, Any]] = (),
    tables: Iterable[Mapping[str, Any]] = (),
    table_rows: Iterable[Mapping[str, Any]] = (),
    table_cells: Iterable[Mapping[str, Any]] = (),
    figures: Iterable[Mapping[str, Any]] = (),
) -> tuple[SourceDocument, ...]:
    """Build document aggregates from the Source parser's flat records."""

    return assemble_source_documents(
        documents=(
            SourceDocument(
                document_id=str(item.get("document_id") or item.get("id") or ""),
                document_order=safe_int(item.get("document_order")) or 0,
                title=str(item.get("title") or ""),
                text=str(item.get("text") or ""),
                creation_date=normalize_optional_text(item.get("creation_date")),
                metadata=_mapping(item.get("metadata")),
                text_units=tuple(
                    (
                        SourceTextUnit(
                            text_unit_id=str(
                                item.get("text_unit_id") or item.get("id") or ""
                            ),
                            text_unit_order=safe_int(item.get("text_unit_order")) or 0,
                            text=str(item.get("text") or ""),
                            n_tokens=safe_int(item.get("n_tokens")),
                            document_ids=_string_tuple(item.get("document_ids")),
                        )
                        for item in item.get("text_units") or ()
                        if isinstance(item, Mapping)
                    )
                ),
                blocks=tuple(
                    (
                        SourceBlock(
                            block_id=str(item.get("block_id") or ""),
                            document_id=str(
                                item.get("document_id") or item.get("id") or ""
                            ),
                            block_type=str(item.get("block_type") or "paragraph"),
                            text=str(item.get("text") or ""),
                            block_order=safe_int(item.get("block_order")) or 0,
                            text_unit_ids=_string_tuple(item.get("text_unit_ids")),
                            page=safe_int(item.get("page")),
                            heading_path=normalize_optional_text(
                                item.get("heading_path")
                            ),
                            heading_level=safe_int(item.get("heading_level")),
                        )
                        for item in item.get("blocks") or ()
                        if isinstance(item, Mapping)
                    )
                ),
                tables=tuple(
                    (
                        SourceTable(
                            table_id=str(item.get("table_id") or ""),
                            document_id=str(item.get("document_id") or ""),
                            table_order=safe_int(item.get("table_order")) or 0,
                            caption_text=normalize_optional_text(
                                item.get("caption_text")
                            ),
                            caption_block_id=normalize_optional_text(
                                item.get("caption_block_id")
                            ),
                            page=safe_int(item.get("page")),
                            heading_path=normalize_optional_text(
                                item.get("heading_path")
                            ),
                            column_headers=_string_tuple(item.get("column_headers")),
                            table_matrix=_table_matrix_tuple(item.get("table_matrix")),
                            header_row_count=max(
                                0,
                                (
                                    safe_int(item.get("header_row_count"))
                                    if safe_int(item.get("header_row_count"))
                                    is not None
                                    else 1
                                ),
                            ),
                            metadata=_mapping(item.get("metadata")),
                        )
                        for item in item.get("tables") or ()
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
                            heading_path=normalize_optional_text(
                                item.get("heading_path")
                            ),
                        )
                        for item in item.get("table_rows") or ()
                        if isinstance(item, Mapping)
                    )
                ),
                table_cells=tuple(
                    (
                        SourceTableCell(
                            cell_id=str(item.get("cell_id") or ""),
                            document_id=str(
                                item.get("document_id") or item.get("id") or ""
                            ),
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
                            header_path=normalize_optional_text(
                                item.get("header_path")
                            ),
                            page=safe_int(item.get("page")),
                            unit_hint=normalize_optional_text(item.get("unit_hint")),
                        )
                        for item in item.get("table_cells") or ()
                        if isinstance(item, Mapping)
                    )
                ),
                figures=tuple(
                    (
                        SourceFigure(
                            figure_id=str(item.get("figure_id") or ""),
                            document_id=str(item.get("document_id") or ""),
                            figure_order=safe_int(item.get("figure_order")) or 0,
                            figure_label=normalize_optional_text(
                                item.get("figure_label")
                            ),
                            caption_text=normalize_optional_text(
                                item.get("caption_text")
                            ),
                            caption_block_id=normalize_optional_text(
                                item.get("caption_block_id")
                            ),
                            page=safe_int(item.get("page")),
                            heading_path=normalize_optional_text(
                                item.get("heading_path")
                            ),
                            image_path=normalize_optional_text(item.get("image_path")),
                            image_mime_type=normalize_optional_text(
                                item.get("image_mime_type")
                            ),
                            image_width=safe_int(item.get("image_width")),
                            image_height=safe_int(item.get("image_height")),
                            asset_sha256=normalize_optional_text(
                                item.get("asset_sha256")
                            ),
                            image_size_bytes=safe_int(item.get("image_size_bytes")),
                            metadata=_mapping(item.get("metadata")),
                        )
                        for item in item.get("figures") or ()
                        if isinstance(item, Mapping)
                    )
                ),
            )
            for item in documents
        ),
        text_units=(
            SourceTextUnit(
                text_unit_id=str(item.get("text_unit_id") or item.get("id") or ""),
                text_unit_order=safe_int(item.get("text_unit_order")) or 0,
                text=str(item.get("text") or ""),
                n_tokens=safe_int(item.get("n_tokens")),
                document_ids=_string_tuple(item.get("document_ids")),
            )
            for item in text_units
        ),
        blocks=(
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
            for item in blocks
        ),
        tables=(
            SourceTable(
                table_id=str(item.get("table_id") or ""),
                document_id=str(item.get("document_id") or ""),
                table_order=safe_int(item.get("table_order")) or 0,
                caption_text=normalize_optional_text(item.get("caption_text")),
                caption_block_id=normalize_optional_text(item.get("caption_block_id")),
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
            for item in tables
        ),
        table_rows=(
            SourceTableRow(
                row_id=str(item.get("row_id") or ""),
                document_id=str(item.get("document_id") or ""),
                table_id=str(item.get("table_id") or ""),
                row_index=safe_int(item.get("row_index")) or 0,
                row_text=str(item.get("row_text") or ""),
                page=safe_int(item.get("page")),
                heading_path=normalize_optional_text(item.get("heading_path")),
            )
            for item in table_rows
        ),
        table_cells=(
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
            for item in table_cells
        ),
        figures=(
            SourceFigure(
                figure_id=str(item.get("figure_id") or ""),
                document_id=str(item.get("document_id") or ""),
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
                metadata=_mapping(item.get("metadata")),
            )
            for item in figures
        ),
    )


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
