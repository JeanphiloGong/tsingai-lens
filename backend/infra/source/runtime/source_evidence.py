from __future__ import annotations

import ast
import json
import re
from typing import Any

import pandas as pd

_METHOD_HEADING_PATTERNS = (
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(materials?\s+and\s+methods?)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(experimental(?:\s+section)?)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(methods?)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(sample\s+preparation)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(fabrication|synthesis)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(实验部分|实验方法|材料与方法|制备方法|方法)$"),
)

_CHARACTERIZATION_HEADING_PATTERNS = (
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(characteri[sz]ation)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(measurements?)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(testing\s+methods?)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(表征|测试方法|性能测试)$"),
)

_OTHER_HEADING_PATTERNS = (
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(introduction|background)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(results?(?:\s+and\s+discussion)?)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(discussion)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(conclusions?)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(references?)$", re.IGNORECASE),
    re.compile(r"^(?:\d+(?:\.\d+)*)?\s*(引言|结果与讨论|结果|讨论|结论|参考文献)$"),
)

_NUMBERED_HEADING_PATTERN = re.compile(r"^(?P<number>\d+(?:\.\d+)*)\s+.+$")
_TABLE_TITLE_PATTERN = re.compile(r"^\s*table\s+([a-z0-9\-]+)\b[:.\-\s]*(.*)$", re.IGNORECASE)
_UNIT_HINT_PATTERN = re.compile(r"\b(MPa|GPa|Pa|%|S/cm|mS/cm|W/mK|wt%|vol%)\b", re.IGNORECASE)


def build_blocks(
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> pd.DataFrame:
    document_records = _build_document_records(documents, text_units)

    rows: list[dict[str, Any]] = []
    for _, row in document_records.iterrows():
        rows.extend(
            _extract_blocks_from_text(
                paper_id=str(row["paper_id"]),
                title=str(row["title"]),
                text=str(row.get("text") or ""),
                text_unit_ids=list(row.get("text_unit_ids") or []),
            )
        )

    return pd.DataFrame(
        rows,
        columns=[
            "block_id",
            "document_id",
            "block_type",
            "text",
            "block_order",
            "text_unit_ids",
            "page",
            "bbox",
            "char_range",
            "heading_path",
            "heading_level",
        ],
    )


def build_table_rows(
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> pd.DataFrame:
    document_records = _build_document_records(documents, text_units)

    rows: list[dict[str, Any]] = []
    for _, row in document_records.iterrows():
        paper_id = str(row["paper_id"])
        lines = [line.strip() for line in re.split(r"\r?\n", str(row.get("text") or "")) if line.strip()]
        rows.extend(_extract_table_rows_from_lines(paper_id, lines))

    return pd.DataFrame(
        rows,
        columns=[
            "row_id",
            "document_id",
            "table_id",
            "row_index",
            "row_text",
            "page",
            "bbox",
            "heading_path",
        ],
    )


def build_table_cells(
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> pd.DataFrame:
    document_records = _build_document_records(documents, text_units)

    rows: list[dict[str, Any]] = []
    for _, row in document_records.iterrows():
        paper_id = str(row["paper_id"])
        lines = [line.strip() for line in re.split(r"\r?\n", str(row.get("text") or "")) if line.strip()]
        rows.extend(_extract_table_cells_from_lines(paper_id, lines))

    return pd.DataFrame(
        rows,
        columns=[
            "cell_id",
            "document_id",
            "table_id",
            "row_index",
            "col_index",
            "cell_text",
            "header_path",
            "page",
            "bbox",
            "char_range",
            "unit_hint",
        ],
    )


def classify_heading(line: str) -> str | None:
    return _classify_heading(line)


def extract_unit_hint(header_path: str | None, cell_text: str) -> str | None:
    return _extract_unit_hint(header_path, cell_text)


def make_table_id(paper_id: str, order: int, title: str | None) -> str:
    return _make_table_id(paper_id, order, title)


def _extract_blocks_from_text(
    paper_id: str,
    title: str,
    text: str,
    text_unit_ids: list[str],
) -> list[dict[str, Any]]:
    lines = [line.strip() for line in re.split(r"\r?\n", text) if line.strip()]
    if not lines and not title:
        return []

    rows: list[dict[str, Any]] = []
    heading_stack: list[str] = []
    block_order = 1
    search_start = 0
    normalized_title = _normalize_line(title)
    normalized_first_line = _normalize_line(lines[0]) if lines else None

    if title and normalized_title and normalized_title != normalized_first_line:
        rows.append(
            _build_block_row(
                paper_id=paper_id,
                block_order=block_order,
                block_type="title",
                text=title,
                text_unit_ids=[],
                page=None,
                bbox=None,
                char_range=None,
                heading_path=title,
                heading_level=0,
            )
        )
        block_order += 1

    for line in lines:
        if _TABLE_TITLE_PATTERN.match(line):
            char_range, search_start = _find_char_range(text, line, search_start)
            rows.append(
                _build_block_row(
                    paper_id=paper_id,
                    block_order=block_order,
                    block_type="table_caption",
                    text=line,
                    text_unit_ids=[],
                    page=None,
                    bbox=None,
                    char_range=char_range,
                    heading_path=_serialize_heading_path(heading_stack),
                    heading_level=None,
                )
            )
            block_order += 1
            continue

        if _split_table_line(line) is not None:
            _, search_start = _find_char_range(text, line, search_start)
            continue

        heading_path = _serialize_heading_path(heading_stack)
        heading_level: int | None = None
        if _looks_like_structural_heading(line):
            heading_level = _infer_heading_level(line)
            heading_stack = _update_heading_path_stack(heading_stack, line, heading_level)
            heading_path = _serialize_heading_path(heading_stack)
            block_type = "heading"
        else:
            block_type = _classify_text_block_type(line)

        char_range, search_start = _find_char_range(text, line, search_start)
        rows.append(
            _build_block_row(
                paper_id=paper_id,
                block_order=block_order,
                block_type=block_type,
                text=line,
                text_unit_ids=text_unit_ids if block_type != "title" else [],
                page=None,
                bbox=None,
                char_range=char_range,
                heading_path=heading_path,
                heading_level=heading_level,
            )
        )
        block_order += 1

    return rows


def _extract_table_rows_from_lines(
    paper_id: str,
    lines: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    heading_stack: list[str] = []
    pending_title: str | None = None
    pending_heading_path: str | None = None
    table_id: str | None = None
    table_counter = 0
    row_index = 0

    for line in lines:
        title_match = _TABLE_TITLE_PATTERN.match(line)
        if title_match:
            pending_title = " ".join(filter(None, [title_match.group(1), title_match.group(2).strip()])).strip()
            pending_heading_path = _serialize_heading_path(heading_stack)
            table_id = None
            row_index = 0
            continue

        cells = _split_table_line(line)
        if cells is not None:
            if table_id is None:
                table_counter += 1
                table_id = _make_table_id(paper_id, table_counter, pending_title)
                row_index = 0
            else:
                rows.append(
                    {
                        "row_id": f"row_{table_id}_{row_index}",
                        "document_id": paper_id,
                        "table_id": table_id,
                        "row_index": row_index,
                        "row_text": " | ".join(cell for cell in cells if cell),
                        "page": None,
                        "bbox": None,
                        "heading_path": pending_heading_path,
                    }
                )
            row_index += 1
            continue

        pending_title = None
        pending_heading_path = None
        table_id = None
        row_index = 0
        if _looks_like_structural_heading(line):
            heading_level = _infer_heading_level(line)
            heading_stack = _update_heading_path_stack(heading_stack, line, heading_level)

    return rows


def _build_block_row(
    *,
    paper_id: str,
    block_order: int,
    block_type: str,
    text: str,
    text_unit_ids: list[str],
    page: int | None,
    bbox: str | None,
    char_range: str | None,
    heading_path: str | None,
    heading_level: int | None,
) -> dict[str, Any]:
    return {
        "block_id": f"blk_{paper_id}_{block_order}",
        "document_id": paper_id,
        "block_type": block_type,
        "text": text,
        "block_order": block_order,
        "text_unit_ids": list(text_unit_ids),
        "page": page,
        "bbox": bbox,
        "char_range": char_range,
        "heading_path": heading_path,
        "heading_level": heading_level,
    }


def _find_char_range(
    source_text: str,
    fragment: str,
    start_index: int,
) -> tuple[str | None, int]:
    if not source_text or not fragment:
        return (None, start_index)

    index = source_text.find(fragment, max(start_index, 0))
    if index < 0 and start_index > 0:
        index = source_text.find(fragment)
    if index < 0:
        return (None, start_index)

    end_index = index + len(fragment)
    return (
        json.dumps(
            {
                "start": index,
                "end": end_index,
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        end_index,
    )


def _looks_like_structural_heading(line: str) -> bool:
    compact = " ".join(str(line or "").split())
    if not compact:
        return False
    if _split_table_line(compact) is not None or _TABLE_TITLE_PATTERN.match(compact):
        return False
    if _classify_heading(compact) is not None:
        return True
    if _NUMBERED_HEADING_PATTERN.match(compact):
        return True
    if len(compact) > 100:
        return False
    if compact.endswith((".", ";", "!", "?", ",")):
        return False
    words = compact.split()
    if len(words) > 12:
        return False
    return compact == compact.title() or compact.isupper()


def _infer_heading_level(line: str) -> int:
    match = _NUMBERED_HEADING_PATTERN.match(" ".join(str(line or "").split()))
    if not match:
        return 1
    return len(str(match.group("number")).split("."))


def _update_heading_path_stack(
    stack: list[str],
    heading: str,
    level: int,
) -> list[str]:
    normalized_heading = " ".join(str(heading or "").split())
    if not normalized_heading:
        return list(stack)

    effective_level = max(1, int(level))
    if effective_level > len(stack) + 1:
        effective_level = len(stack) + 1
    return [*stack[: effective_level - 1], normalized_heading]


def _serialize_heading_path(stack: list[str]) -> str | None:
    values = [str(item).strip() for item in stack if str(item).strip()]
    if not values:
        return None
    return " > ".join(values)


def _classify_text_block_type(line: str) -> str:
    stripped = str(line or "").strip()
    if stripped.startswith(("- ", "* ", "• ")):
        return "list_item"
    return "paragraph"


def _normalize_line(value: Any) -> str | None:
    text = _coerce_optional_text(value)
    if text is None:
        return None
    return " ".join(text.split()).casefold()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_table_cells_from_lines(
    paper_id: str,
    lines: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pending_title: str | None = None
    header_cells: list[str] | None = None
    table_id: str | None = None
    table_counter = 0
    row_index = 0

    for line in lines:
        title_match = _TABLE_TITLE_PATTERN.match(line)
        if title_match:
            pending_title = " ".join(filter(None, [title_match.group(1), title_match.group(2).strip()])).strip()
            header_cells = None
            table_id = None
            row_index = 0
            continue

        cells = _split_table_line(line)
        if cells is None:
            pending_title = None
            header_cells = None
            table_id = None
            row_index = 0
            continue

        if table_id is None:
            table_counter += 1
            table_id = _make_table_id(paper_id, table_counter, pending_title)
            header_cells = [cell or f"column_{index + 1}" for index, cell in enumerate(cells)]
            source_cells = header_cells
        else:
            source_cells = cells

        for col_index, cell_text in enumerate(source_cells, start=1):
            header_path = None if row_index == 0 else _resolve_header_path(header_cells, col_index - 1)
            rows.append(
                {
                    "cell_id": f"cell_{table_id}_{row_index}_{col_index}",
                    "document_id": paper_id,
                    "table_id": table_id,
                    "row_index": row_index,
                    "col_index": col_index - 1,
                    "cell_text": cell_text,
                    "header_path": header_path,
                    "page": None,
                    "bbox": None,
                    "char_range": None,
                    "unit_hint": _extract_unit_hint(header_path, cell_text),
                }
            )
        row_index += 1

    return rows


def _split_table_line(line: str) -> list[str] | None:
    stripped = line.strip()
    if "|" in stripped:
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len([cell for cell in cells if cell]) >= 2:
            return cells
    if "\t" in stripped:
        cells = [cell.strip() for cell in stripped.split("\t")]
        if len([cell for cell in cells if cell]) >= 2:
            return cells
    return None


def _resolve_header_path(header_cells: list[str] | None, index: int) -> str | None:
    if not header_cells or index >= len(header_cells):
        return None
    text = str(header_cells[index] or "").strip()
    return text or None


def _extract_unit_hint(header_path: str | None, cell_text: str) -> str | None:
    for source in (header_path or "", cell_text):
        match = _UNIT_HINT_PATTERN.search(str(source or ""))
        if match:
            return match.group(1)
    return None


def _make_table_id(paper_id: str, order: int, title: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(title or "").lower()).strip("_")
    if not slug:
        slug = f"table_{order}"
    return f"tbl_{paper_id}_{order}_{slug}"


def _build_document_records(
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> pd.DataFrame:
    text_unit_ids_by_doc: dict[str, list[str]] = {}
    if text_units is not None and {"id", "text"}.issubset(text_units.columns):
        for _, row in text_units.iterrows():
            text_unit_id = str(row.get("id"))
            for doc_id in _listify(row.get("document_ids")):
                text_unit_ids_by_doc.setdefault(str(doc_id), []).append(text_unit_id)

    rows: list[dict[str, Any]] = []
    for _, row in documents.iterrows():
        paper_id = str(row.get("id"))
        text = str(row.get("text") or "").strip()
        if not text and text_units is not None:
            text = _join_text_units_for_document(text_units, paper_id)
        rows.append(
            {
                "paper_id": paper_id,
                "title": _coerce_optional_text(row.get("title")) or paper_id,
                "text": text,
                "text_unit_ids": text_unit_ids_by_doc.get(paper_id, []),
            }
        )
    return pd.DataFrame(rows, columns=["paper_id", "title", "text", "text_unit_ids"])


def _join_text_units_for_document(text_units: pd.DataFrame, paper_id: str) -> str:
    matched: list[str] = []
    for _, row in text_units.iterrows():
        if paper_id not in {str(item) for item in _listify(row.get("document_ids"))}:
            continue
        text = str(row.get("text") or "").strip()
        if text:
            matched.append(text)
    return "\n".join(matched)


def _coerce_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        converted = value.tolist()
        if converted is not value:
            return _listify(converted)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                return [text]
            if isinstance(parsed, list):
                return parsed
        return [text]
    if isinstance(value, float) and pd.isna(value):
        return []
    return [value]


def _classify_heading(line: str) -> str | None:
    compact = " ".join(line.split())
    if len(compact) > 80:
        return None
    if any(pattern.match(compact) for pattern in _METHOD_HEADING_PATTERNS):
        return "methods"
    if any(pattern.match(compact) for pattern in _CHARACTERIZATION_HEADING_PATTERNS):
        return "characterization"
    if any(pattern.match(compact) for pattern in _OTHER_HEADING_PATTERNS):
        return "other"
    return None
