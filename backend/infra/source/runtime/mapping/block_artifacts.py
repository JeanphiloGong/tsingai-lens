from __future__ import annotations

from typing import Any

import pandas as pd

from infra.source.contracts.artifact_schemas import BLOCKS_FINAL_COLUMNS
from infra.source.runtime.mapping.layout_binding import (
    first_page,
    normalize_optional_text,
    serialize_char_range,
    serialize_prov_bbox,
)


def build_pdf_blocks(
    *,
    document_id: str,
    title: str,
    text_items: list[dict[str, Any]],
    figure_caption_refs: set[str],
    table_caption_refs: set[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    heading_stack: list[str] = []
    order = 1
    saw_title = False

    if not any(str(item.get("label") or "").lower() == "title" for item in text_items) and title:
        rows.append(
            {
                "block_id": f"blk_{document_id}_{order}",
                "document_id": document_id,
                "block_type": "title",
                "text": title,
                "block_order": order,
                "text_unit_ids": [],
                "page": None,
                "bbox": None,
                "char_range": None,
                "heading_path": title,
                "heading_level": 0,
            }
        )
        order += 1

    for item in text_items:
        label = str(item["label"] or "").lower()
        if label == "title":
            saw_title = True
        block_type = _map_docling_block_type(
            label,
            item["text"],
            caption_ref=item.get("ref"),
            figure_caption_refs=figure_caption_refs,
            table_caption_refs=table_caption_refs,
        )
        heading_path: str | None = None
        heading_level: int | None = None
        if block_type == "heading":
            heading_level = _infer_heading_level_from_text(item["text"])
            heading_stack = _update_heading_stack(heading_stack, item["text"], heading_level)
            heading_path = " > ".join(heading_stack)
        elif block_type == "title":
            heading_path = item["text"]
        else:
            heading_path = " > ".join(heading_stack) if heading_stack else None
        block_id = f"blk_{document_id}_{order}"
        rows.append(
            {
                "block_id": block_id,
                "document_id": document_id,
                "block_type": block_type,
                "text": item["text"],
                "block_order": order,
                "text_unit_ids": [item["text_unit_id"]] if item.get("text_unit_id") else [],
                "page": item["page"],
                "bbox": item.get("bbox"),
                "char_range": item["char_range"],
                "heading_path": heading_path,
                "heading_level": heading_level,
            }
        )
        item["block_id"] = block_id
        item["heading_path"] = heading_path
        order += 1

    if not saw_title and title and not rows:
        rows.append(
            {
                "block_id": f"blk_{document_id}_{order}",
                "document_id": document_id,
                "block_type": "title",
                "text": title,
                "block_order": order,
                "text_unit_ids": [],
                "page": None,
                "bbox": None,
                "char_range": None,
                "heading_path": title,
                "heading_level": 0,
            }
        )

    return pd.DataFrame(rows, columns=BLOCKS_FINAL_COLUMNS)


def collect_caption_ref_sets(document: Any) -> tuple[set[str], set[str]]:
    figure_caption_refs: set[str] = set()
    table_caption_refs: set[str] = set()
    for picture in getattr(document, "pictures", []) or []:
        for ref in getattr(picture, "captions", []) or []:
            cref = normalize_optional_text(getattr(ref, "cref", None))
            if cref is not None:
                figure_caption_refs.add(cref)
    for table in getattr(document, "tables", []) or []:
        for ref in getattr(table, "captions", []) or []:
            cref = normalize_optional_text(getattr(ref, "cref", None))
            if cref is not None:
                table_caption_refs.add(cref)
    return figure_caption_refs, table_caption_refs


def collect_pdf_text_items(document: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(getattr(document, "texts", []) or []):
        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "index": index,
                "ref": f"#/texts/{index}",
                "text": text,
                "label": str(getattr(item, "label", "") or ""),
                "page": first_page(getattr(item, "prov", None)),
                "bbox": serialize_prov_bbox(getattr(item, "prov", None)),
                "char_range": serialize_char_range(getattr(item, "prov", None)),
            }
        )
    return rows


def _map_docling_block_type(
    label: str,
    text: str,
    *,
    caption_ref: str | None,
    figure_caption_refs: set[str],
    table_caption_refs: set[str],
) -> str:
    lowered = str(label or "").lower()
    if lowered == "title":
        return "title"
    if lowered in {"section_header", "heading"}:
        return "heading"
    if "caption" in lowered:
        if caption_ref and caption_ref in figure_caption_refs:
            return "figure_caption"
        if caption_ref and caption_ref in table_caption_refs:
            return "table_caption"
        normalized_text = " ".join(str(text or "").split()).lower()
        if normalized_text.startswith(("table ", "tab. ")):
            return "table_caption"
        if normalized_text.startswith(("figure ", "fig. ", "fig ")):
            return "figure_caption"
        return "figure_caption"
    if "list" in lowered:
        return "list_item"
    return "paragraph"


def _infer_heading_level_from_text(text: str) -> int:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return 1
    parts = normalized.split(maxsplit=1)
    if parts and all(part.isdigit() for part in parts[0].split(".")):
        return len(parts[0].split("."))
    return 1


def _update_heading_stack(
    stack: list[str],
    heading: str,
    level: int,
) -> list[str]:
    normalized = " ".join(str(heading or "").split())
    if not normalized:
        return list(stack)
    effective_level = max(1, int(level or 1))
    if effective_level > len(stack) + 1:
        effective_level = len(stack) + 1
    return [*stack[: effective_level - 1], normalized]
