from __future__ import annotations

from typing import Any

import pandas as pd

from domain.source import (
    SourceBlock,
    SourceBoundingBox,
    SourceCharRange,
    normalize_optional_text,
    update_heading_stack,
)
from infra.source.contracts.artifact_schemas import BLOCKS_FINAL_COLUMNS
from infra.source.runtime.mapping.layout_binding import (
    first_bbox,
    first_page,
    serialize_char_range,
    serialize_prov_bbox,
)
from infra.source.runtime.mapping.text_quality import is_garbled_pdf_text


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
            SourceBlock(
                block_id=f"blk_{document_id}_{order}",
                document_id=document_id,
                block_type="title",
                text=title,
                block_order=order,
                heading_path=title,
                heading_level=0,
            ).to_record()
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
            heading_stack = update_heading_stack(heading_stack, item["text"], heading_level)
            heading_path = " > ".join(heading_stack)
        elif block_type == "title":
            heading_path = item["text"]
        else:
            heading_path = " > ".join(heading_stack) if heading_stack else None
        block_id = f"blk_{document_id}_{order}"
        rows.append(
            SourceBlock(
                block_id=block_id,
                document_id=document_id,
                block_type=block_type,
                text=item["text"],
                block_order=order,
                text_unit_ids=tuple(
                    [item["text_unit_id"]] if item.get("text_unit_id") else []
                ),
                page=item["page"],
                bbox=SourceBoundingBox.from_value(item.get("bbox")),
                char_range=SourceCharRange.from_value(item["char_range"]),
                heading_path=heading_path,
                heading_level=heading_level,
            ).to_record()
        )
        item["block_id"] = block_id
        item["heading_path"] = heading_path
        order += 1

    if not saw_title and title and not rows:
        rows.append(
            SourceBlock(
                block_id=f"blk_{document_id}_{order}",
                document_id=document_id,
                block_type="title",
                text=title,
                block_order=order,
                heading_path=title,
                heading_level=0,
            ).to_record()
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
    figure_caption_refs, table_caption_refs = collect_caption_ref_sets(document)
    caption_refs = figure_caption_refs | table_caption_refs
    figure_regions = _collect_figure_regions(document)
    for index, item in enumerate(getattr(document, "texts", []) or []):
        text = str(getattr(item, "text", "") or "").strip()
        if not text or is_garbled_pdf_text(text):
            continue
        ref = f"#/texts/{index}"
        provenance = getattr(item, "prov", None)
        page = first_page(provenance)
        bbox = SourceBoundingBox.from_value(first_bbox(provenance))
        if ref not in caption_refs and _is_inside_figure(page, bbox, figure_regions):
            continue
        rows.append(
            {
                "index": index,
                "ref": ref,
                "text": text,
                "label": str(getattr(item, "label", "") or ""),
                "page": page,
                "bbox": serialize_prov_bbox(provenance),
                "char_range": serialize_char_range(provenance),
            }
        )
    return rows


def _collect_figure_regions(
    document: Any,
) -> list[tuple[int, SourceBoundingBox]]:
    regions: list[tuple[int, SourceBoundingBox]] = []
    for picture in getattr(document, "pictures", []) or []:
        provenance = getattr(picture, "prov", None)
        page = first_page(provenance)
        bbox = SourceBoundingBox.from_value(first_bbox(provenance))
        if page is not None and bbox is not None:
            regions.append((page, bbox))
    return regions


def _is_inside_figure(
    page: int | None,
    bbox: SourceBoundingBox | None,
    figure_regions: list[tuple[int, SourceBoundingBox]],
) -> bool:
    if page is None or bbox is None:
        return False
    for figure_page, figure_bbox in figure_regions:
        if figure_page != page:
            continue
        if (
            bbox.coord_origin
            and figure_bbox.coord_origin
            and bbox.coord_origin != figure_bbox.coord_origin
        ):
            continue
        if (
            min(bbox.l, bbox.r) >= min(figure_bbox.l, figure_bbox.r)
            and max(bbox.l, bbox.r) <= max(figure_bbox.l, figure_bbox.r)
            and min(bbox.t, bbox.b) >= min(figure_bbox.t, figure_bbox.b)
            and max(bbox.t, bbox.b) <= max(figure_bbox.t, figure_bbox.b)
        ):
            return True
    return False


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
