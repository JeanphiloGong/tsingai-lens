from __future__ import annotations

import ast
import re
from typing import Any
from uuid import uuid4

import pandas as pd

from services.protocol_source_service import build_document_records

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


def build_sections(
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> pd.DataFrame:
    document_records = build_document_records(documents, text_units)
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
            "confidence",
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
                "section_id": str(uuid4()),
                "paper_id": paper_id,
                "title": title,
                "section_type": section_type,
                "heading": heading,
                "text": body,
                "order": output_order,
                "source_mode": "heading",
                "text_unit_ids": text_unit_ids,
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
                "section_id": str(uuid4()),
                "paper_id": paper_id,
                "title": title,
                "section_type": pending_type,
                "heading": f"synthetic_{pending_type}",
                "text": "\n".join(pending_texts),
                "order": len(sections) + 1,
                "source_mode": "text_unit_fallback",
                "text_unit_ids": pending_ids[:],
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


def _group_text_units_by_document(text_units: pd.DataFrame | None) -> dict[str, list[dict[str, Any]]]:
    if text_units is None or text_units.empty:
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for _, row in text_units.iterrows():
        doc_ids = row.get("document_ids")
        if isinstance(doc_ids, list):
            values = [str(item) for item in doc_ids]
        elif isinstance(doc_ids, str) and doc_ids.strip().startswith("[") and doc_ids.strip().endswith("]"):
            try:
                parsed = ast.literal_eval(doc_ids)
            except (ValueError, SyntaxError):
                values = [doc_ids]
            else:
                values = [str(item) for item in parsed] if isinstance(parsed, list) else [doc_ids]
        elif doc_ids is None or (isinstance(doc_ids, float) and pd.isna(doc_ids)):
            values = []
        else:
            values = [str(doc_ids)]
        for doc_id in values:
            grouped.setdefault(doc_id, []).append(dict(row))
    return grouped


def _classify_heading(line: str) -> str | None:
    compact = " ".join(line.split())
    if len(compact) > 90:
        return None
    for pattern in _METHOD_HEADING_PATTERNS:
        if pattern.match(compact):
            return "methods"
    for pattern in _CHARACTERIZATION_HEADING_PATTERNS:
        if pattern.match(compact):
            return "characterization"
    for pattern in _OTHER_HEADING_PATTERNS:
        if pattern.match(compact):
            return "other"
    return None


def _classify_text_unit(text: str) -> str | None:
    lowered = text.lower()
    method_score = sum(1 for token in _METHOD_HINTS if token in lowered)
    characterization_score = sum(1 for token in _CHARACTERIZATION_HINTS if token in lowered)
    if method_score <= 0 and characterization_score <= 0:
        return None
    if characterization_score > method_score:
        return "characterization"
    return "methods"
