from __future__ import annotations

import ast
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

_METHOD_HINTS = (
    "stir",
    "mix",
    "dissolve",
    "synthes",
    "fabricat",
    "prepare",
    "hydrothermal",
    "solvothermal",
    "calcine",
    "anneal",
    "wash",
    "dry",
    "heated",
    "prepared",
    "加入",
    "搅拌",
    "溶解",
    "制备",
    "退火",
    "烧结",
    "洗涤",
    "干燥",
)

_CHARACTERIZATION_HINTS = (
    "xrd",
    "sem",
    "tem",
    "xps",
    "raman",
    "ftir",
    "dsc",
    "tga",
    "tensile",
    "flexural",
    "compression",
    "fatigue",
    "thermal conductivity",
    "characteriz",
    "测试",
    "表征",
    "拉伸",
    "压缩",
    "疲劳",
    "热导",
    "热稳定",
)

_TABLE_TITLE_PATTERN = re.compile(r"^\s*table\s+([a-z0-9\-]+)\b[:.\-\s]*(.*)$", re.IGNORECASE)
_UNIT_HINT_PATTERN = re.compile(r"\b(MPa|GPa|Pa|%|S/cm|mS/cm|W/mK|wt%|vol%)\b", re.IGNORECASE)


def build_sections(
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> pd.DataFrame:
    document_records = _build_document_records(documents, text_units)
    text_units_by_doc = _group_text_units_by_document(text_units)

    sections: list[dict[str, Any]] = []
    for _, row in document_records.iterrows():
        paper_id = str(row["paper_id"])
        title = str(row["title"])
        text = str(row["text"] or "")
        extracted = _extract_sections_from_text(
            paper_id=paper_id,
            title=title,
            text=text,
            text_unit_ids=list(row.get("text_unit_ids") or []),
        )
        if not extracted:
            extracted = _fallback_sections_from_text_units(
                paper_id=paper_id,
                title=title,
                units=text_units_by_doc.get(paper_id, []),
            )
        sections.extend(extracted)

    return pd.DataFrame(
        sections,
        columns=[
            "section_id",
            "paper_id",
            "title",
            "section_type",
            "heading",
            "text",
            "order",
            "source_mode",
            "text_unit_ids",
            "page",
            "char_range",
            "confidence",
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


def _extract_sections_from_text(
    paper_id: str,
    title: str,
    text: str,
    text_unit_ids: list[str],
) -> list[dict[str, Any]]:
    lines = [line.strip() for line in re.split(r"\r?\n", text) if line.strip()]
    if not lines:
        return []

    headings: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        section_type = _classify_heading(line)
        if section_type is None:
            continue
        headings.append((index, line, section_type))

    if not headings:
        return []

    sections: list[dict[str, Any]] = []
    output_order = 0
    for order, (line_index, heading, section_type) in enumerate(headings, start=1):
        end_index = headings[order][0] if order < len(headings) else len(lines)
        body = "\n".join(lines[line_index + 1 : end_index]).strip()
        if section_type not in {"methods", "characterization"} or len(body) < 30:
            continue
        output_order += 1
        sections.append(
            {
                "section_id": _make_section_id(paper_id, section_type, output_order, heading),
                "paper_id": paper_id,
                "title": title,
                "section_type": section_type,
                "heading": heading,
                "text": body,
                "order": output_order,
                "source_mode": "heading",
                "text_unit_ids": text_unit_ids,
                "page": None,
                "char_range": None,
                "confidence": 0.95 if section_type == "methods" else 0.9,
            }
        )
    return sections


def _fallback_sections_from_text_units(
    paper_id: str,
    title: str,
    units: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not units:
        return []

    sections: list[dict[str, Any]] = []
    pending_type: str | None = None
    pending_texts: list[str] = []
    pending_ids: list[str] = []

    def flush() -> None:
        nonlocal pending_type, pending_texts, pending_ids
        if pending_type is None or not pending_texts:
            pending_type = None
            pending_texts = []
            pending_ids = []
            return
        sections.append(
            {
                "section_id": _make_section_id(
                    paper_id,
                    pending_type,
                    len(sections) + 1,
                    f"synthetic_{pending_type}",
                ),
                "paper_id": paper_id,
                "title": title,
                "section_type": pending_type,
                "heading": f"synthetic_{pending_type}",
                "text": "\n".join(pending_texts),
                "order": len(sections) + 1,
                "source_mode": "text_unit_fallback",
                "text_unit_ids": pending_ids[:],
                "page": None,
                "char_range": None,
                "confidence": 0.65 if pending_type == "methods" else 0.6,
            }
        )
        pending_type = None
        pending_texts = []
        pending_ids = []

    for unit in units:
        text = str(unit.get("text") or "").strip()
        if not text:
            continue
        unit_type = _classify_text_unit(text)
        if unit_type is None:
            flush()
            continue
        if pending_type not in (None, unit_type):
            flush()
        pending_type = unit_type
        pending_texts.append(text)
        pending_ids.append(str(unit.get("id")))
    flush()
    return sections


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


def _group_text_units_by_document(
    text_units: pd.DataFrame | None,
) -> dict[str, list[dict[str, Any]]]:
    if text_units is None or text_units.empty:
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for _, row in text_units.iterrows():
        for doc_id in _listify(row.get("document_ids")):
            grouped.setdefault(str(doc_id), []).append(dict(row))
    return grouped


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


def _classify_text_unit(text: str) -> str | None:
    lowered = text.lower()
    method_hits = sum(1 for hint in _METHOD_HINTS if hint in lowered)
    characterization_hits = sum(1 for hint in _CHARACTERIZATION_HINTS if hint in lowered)
    if method_hits >= 2 or ("under" in lowered and any(unit in lowered for unit in (" c", "°c", " h", " min"))):
        return "methods"
    if characterization_hits >= 1:
        return "characterization"
    return None


def _make_section_id(
    paper_id: str,
    section_type: str,
    order: int,
    heading: str,
) -> str:
    raw_heading = " ".join(str(heading or section_type or f"section_{order}").split()).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw_heading).strip("_")
    if not slug:
        slug = f"section_{order}"
    return f"sec_{paper_id}_{section_type}_{order}_{slug}"
