from __future__ import annotations

from typing import Any

import pandas as pd

from infra.source.contracts.artifact_schemas import (
    TABLE_CELLS_FINAL_COLUMNS,
    TABLES_FINAL_COLUMNS,
    TABLE_ROWS_FINAL_COLUMNS,
)
from infra.source.runtime.hashing import gen_sha512_hash
from infra.source.runtime.mapping.layout_binding import (
    build_heading_blocks,
    build_table_caption_blocks,
    find_nearest_caption_block,
    first_non_null,
    first_page,
    merge_bbox_payloads,
    normalize_label,
    normalize_optional_text,
    resolve_heading_path_for_target,
    safe_int,
    serialize_bbox,
    serialize_prov_bbox,
)
from infra.source.runtime.source_evidence import extract_unit_hint, make_table_id


def build_pdf_tables(
    *,
    document_id: str,
    document: Any,
    blocks: pd.DataFrame,
    text_items: list[dict[str, Any]],
) -> pd.DataFrame:
    tables = getattr(document, "tables", []) or []
    if not tables:
        return pd.DataFrame(columns=TABLES_FINAL_COLUMNS)

    heading_blocks = build_heading_blocks(blocks)
    text_item_by_ref = {
        str(item.get("ref")): item
        for item in text_items
        if str(item.get("ref") or "").strip()
    }
    table_caption_blocks = build_table_caption_blocks(blocks)
    used_caption_block_ids: set[str] = set()
    rows: list[dict[str, Any]] = []

    for table_order, table in enumerate(tables, start=1):
        table_id = make_table_id(document_id, table_order, None)
        page = first_page(getattr(table, "prov", None))
        bbox = serialize_prov_bbox(getattr(table, "prov", None))
        caption_text, caption_ref, linkage_method = _extract_table_caption(
            table=table,
            document=document,
        )
        caption_block_id = None
        if caption_ref is not None:
            caption_item = text_item_by_ref.get(caption_ref)
            if caption_item is not None:
                caption_block_id = normalize_optional_text(caption_item.get("block_id"))
        if caption_block_id is None:
            fallback_block = find_nearest_caption_block(
                page=page,
                target_bbox=bbox,
                caption_blocks=table_caption_blocks,
                used_block_ids=used_caption_block_ids,
            )
            if fallback_block is not None:
                caption_block_id = str(fallback_block["block_id"])
                caption_text = caption_text or normalize_optional_text(
                    fallback_block.get("text")
                )
                linkage_method = "same_page_nearest_caption"
        if caption_block_id is not None:
            used_caption_block_ids.add(caption_block_id)

        matrix = build_docling_table_matrix(table)
        row_count = len(matrix)
        col_count = max((len(row) for row in matrix), default=0)
        header_paths = build_docling_header_paths(table)
        column_headers = [
            header_paths.get(col_index) or f"column_{col_index + 1}"
            for col_index in range(col_count)
        ]

        rows.append(
            {
                "table_id": table_id,
                "document_id": document_id,
                "table_order": table_order,
                "caption_text": caption_text,
                "caption_block_id": caption_block_id,
                "page": page,
                "bbox": bbox,
                "heading_path": resolve_heading_path_for_target(
                    page=page,
                    target_bbox=bbox,
                    heading_blocks=heading_blocks,
                ),
                "row_count": row_count,
                "col_count": col_count,
                "column_headers": column_headers,
                "table_matrix": matrix,
                "table_markdown": render_markdown_table(matrix, column_headers),
                "table_text": render_plain_table_text(matrix),
                "metadata": {
                    "docling_ref": f"#/tables/{table_order - 1}",
                    "table_label": normalize_label(getattr(table, "label", None)),
                    "caption_linkage_method": linkage_method,
                    "column_header_count": len(header_paths),
                },
            }
        )

    return pd.DataFrame(rows, columns=TABLES_FINAL_COLUMNS)


def build_pdf_table_cells(*, document_id: str, document: Any) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for table_index, table in enumerate(getattr(document, "tables", []) or [], start=1):
        table_id = make_table_id(document_id, table_index, None)
        header_paths = build_docling_header_paths(table)
        table_page = first_page(getattr(table, "prov", None))

        for cell_index, cell in enumerate(getattr(getattr(table, "data", None), "table_cells", []) or []):
            row_index = int(getattr(cell, "start_row_offset_idx", 0))
            col_index = int(getattr(cell, "start_col_offset_idx", 0))
            cell_text = str(getattr(cell, "text", "") or "").strip()
            header_path = None
            if not bool(getattr(cell, "column_header", False)) and not bool(getattr(cell, "row_header", False)):
                header_path = header_paths.get(col_index)
            rows.append(
                {
                    "cell_id": gen_sha512_hash(
                        {
                            "document_id": document_id,
                            "table_id": table_id,
                            "cell_index": cell_index,
                            "row_index": row_index,
                            "col_index": col_index,
                            "text": cell_text,
                        },
                        ["document_id", "table_id", "cell_index", "row_index", "col_index", "text"],
                    ),
                    "id": document_id,
                    "table_id": table_id,
                    "row_index": row_index,
                    "col_index": col_index,
                    "cell_text": cell_text,
                    "header_path": header_path,
                    "page": table_page,
                    "bbox": serialize_bbox(getattr(cell, "bbox", None)),
                    "char_range": None,
                    "unit_hint": extract_unit_hint(header_path, cell_text),
                }
            )
    return pd.DataFrame(rows, columns=TABLE_CELLS_FINAL_COLUMNS)


def build_pdf_table_rows(
    *,
    document_id: str,
    blocks: pd.DataFrame,
    table_cells: pd.DataFrame | None,
) -> pd.DataFrame:
    if table_cells is None or table_cells.empty:
        return pd.DataFrame(columns=TABLE_ROWS_FINAL_COLUMNS)

    heading_blocks = build_heading_blocks(blocks)

    rows: list[dict[str, Any]] = []
    for table_id, table_frame in table_cells.groupby("table_id", sort=False):
        row_indices = {
            int(value)
            for value in table_frame["row_index"].dropna().tolist()
        }
        for row_index in sorted(row_indices):
            row_frame = table_frame[table_frame["row_index"].astype(int) == row_index]
            if row_frame["header_path"].isna().all():
                continue
            ordered_cells = row_frame.sort_values("col_index")
            row_text = " | ".join(
                str(value).strip()
                for value in ordered_cells["cell_text"].tolist()
                if str(value).strip()
            )
            if not row_text:
                continue
            page = first_non_null(ordered_cells["page"].tolist())
            row_bbox = merge_bbox_payloads(ordered_cells["bbox"].tolist())
            rows.append(
                {
                    "row_id": f"row_{document_id}_{table_id}_{row_index}",
                    "document_id": document_id,
                    "table_id": str(table_id),
                    "row_index": row_index,
                    "row_text": row_text,
                    "page": page,
                    "bbox": row_bbox,
                    "heading_path": resolve_heading_path_for_target(
                        page=page,
                        target_bbox=row_bbox,
                        heading_blocks=heading_blocks,
                    ),
                }
            )

    return pd.DataFrame(rows, columns=TABLE_ROWS_FINAL_COLUMNS)


def build_docling_header_paths(table: Any) -> dict[int, str]:
    header_by_col: dict[int, list[str]] = {}
    for cell in getattr(getattr(table, "data", None), "table_cells", []) or []:
        if not bool(getattr(cell, "column_header", False)):
            continue
        text = str(getattr(cell, "text", "") or "").strip()
        if not text:
            continue
        start = int(getattr(cell, "start_col_offset_idx", 0))
        end = int(getattr(cell, "end_col_offset_idx", start + 1))
        if end <= start:
            end = start + 1
        for col_index in range(start, end):
            values = header_by_col.setdefault(col_index, [])
            if text not in values:
                values.append(text)
    return {
        col_index: " > ".join(values)
        for col_index, values in header_by_col.items()
        if values
    }


def build_docling_table_matrix(table: Any) -> list[list[str]]:
    cells = list(getattr(getattr(table, "data", None), "table_cells", []) or [])
    if not cells:
        return []

    row_count = safe_int(getattr(getattr(table, "data", None), "num_rows", None)) or 0
    col_count = safe_int(getattr(getattr(table, "data", None), "num_cols", None)) or 0
    for cell in cells:
        start_row = int(getattr(cell, "start_row_offset_idx", 0))
        end_row = int(getattr(cell, "end_row_offset_idx", start_row + 1))
        start_col = int(getattr(cell, "start_col_offset_idx", 0))
        end_col = int(getattr(cell, "end_col_offset_idx", start_col + 1))
        row_count = max(row_count, end_row, start_row + 1)
        col_count = max(col_count, end_col, start_col + 1)

    if row_count <= 0 or col_count <= 0:
        return []

    matrix = [["" for _ in range(col_count)] for _ in range(row_count)]
    for cell in cells:
        text = " ".join(str(getattr(cell, "text", "") or "").split())
        start_row = int(getattr(cell, "start_row_offset_idx", 0))
        end_row = int(getattr(cell, "end_row_offset_idx", start_row + 1))
        start_col = int(getattr(cell, "start_col_offset_idx", 0))
        end_col = int(getattr(cell, "end_col_offset_idx", start_col + 1))
        if end_row <= start_row:
            end_row = start_row + 1
        if end_col <= start_col:
            end_col = start_col + 1
        for row_index in range(max(start_row, 0), min(end_row, row_count)):
            for col_index in range(max(start_col, 0), min(end_col, col_count)):
                existing = matrix[row_index][col_index]
                matrix[row_index][col_index] = (
                    text if not existing or existing == text else f"{existing} {text}"
                )
    return matrix


def render_markdown_table(matrix: list[list[str]], column_headers: list[str]) -> str | None:
    if not matrix:
        return None

    col_count = max(len(column_headers), max((len(row) for row in matrix), default=0))
    if col_count <= 0:
        return None
    normalized_rows = [_normalize_table_row(row, col_count) for row in matrix]
    header = _normalize_table_row(normalized_rows[0] if normalized_rows else column_headers, col_count)
    if not any(header):
        header = _normalize_table_row(column_headers, col_count)
    if not any(header):
        header = [f"column_{index + 1}" for index in range(col_count)]

    body_rows = normalized_rows[1:] if normalized_rows else []
    lines = [
        "| " + " | ".join(_escape_markdown_cell(value) for value in header) + " |",
        "| " + " | ".join("---" for _ in range(col_count)) + " |",
    ]
    for row in body_rows:
        lines.append("| " + " | ".join(_escape_markdown_cell(value) for value in row) + " |")
    return "\n".join(lines)


def render_plain_table_text(matrix: list[list[str]]) -> str | None:
    if not matrix:
        return None
    lines = []
    for row in matrix:
        line = " | ".join(str(cell).strip() for cell in row if str(cell).strip())
        if line:
            lines.append(line)
    return "\n".join(lines) or None


def _extract_table_caption(*, table: Any, document: Any) -> tuple[str | None, str | None, str]:
    caption_text = None
    if hasattr(table, "caption_text"):
        caption_text = normalize_optional_text(table.caption_text(document))
    caption_ref = None
    for ref in getattr(table, "captions", []) or []:
        caption_ref = normalize_optional_text(getattr(ref, "cref", None))
        if caption_ref is None:
            continue
        if caption_text is not None:
            return caption_text, caption_ref, "docling_caption_ref"
        try:
            caption_text = normalize_optional_text(ref.resolve(document).text)
        except Exception:  # noqa: BLE001
            caption_text = None
        return caption_text, caption_ref, "docling_caption_ref"
    return caption_text, caption_ref, "none"


def _normalize_table_row(row: list[str], col_count: int) -> list[str]:
    values = [" ".join(str(value or "").split()) for value in row[:col_count]]
    if len(values) < col_count:
        values.extend([""] * (col_count - len(values)))
    return values


def _escape_markdown_cell(value: str) -> str:
    return str(value or "").replace("|", "\\|").strip()
