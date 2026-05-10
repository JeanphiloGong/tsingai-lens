from __future__ import annotations

import json
from typing import Any

import pandas as pd


def first_page(provenance: Any) -> int | None:
    if not provenance:
        return None
    first = provenance[0]
    page_no = getattr(first, "page_no", None)
    return int(page_no) if page_no is not None else None


def serialize_char_range(provenance: Any) -> str | None:
    if not provenance:
        return None
    first = provenance[0]
    charspan = getattr(first, "charspan", None)
    if not charspan:
        return None
    return json.dumps(
        {
            "start": int(charspan[0]),
            "end": int(charspan[1]),
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def serialize_prov_bbox(provenance: Any) -> str | None:
    if not provenance:
        return None
    first = provenance[0]
    return serialize_bbox(getattr(first, "bbox", None))


def serialize_bbox(bbox: Any) -> str | None:
    if bbox is None:
        return None
    return json.dumps(
        {
            "l": float(getattr(bbox, "l", 0.0)),
            "t": float(getattr(bbox, "t", 0.0)),
            "r": float(getattr(bbox, "r", 0.0)),
            "b": float(getattr(bbox, "b", 0.0)),
            "coord_origin": str(getattr(getattr(bbox, "coord_origin", None), "value", None) or ""),
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def first_bbox(provenance: Any) -> Any | None:
    if not provenance:
        return None
    first = provenance[0]
    return getattr(first, "bbox", None)


def first_non_null(values: list[Any]) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, float) and pd.isna(value):
            continue
        return value
    return None


def merge_bbox_payloads(values: list[Any]) -> str | None:
    payloads = []
    for value in values:
        if not value:
            continue
        if isinstance(value, str):
            payloads.append(json.loads(value))
        elif isinstance(value, dict):
            payloads.append(value)
    if not payloads:
        return None
    return json.dumps(
        {
            "l": min(float(payload.get("l", 0.0)) for payload in payloads),
            "t": min(float(payload.get("t", 0.0)) for payload in payloads),
            "r": max(float(payload.get("r", 0.0)) for payload in payloads),
            "b": max(float(payload.get("b", 0.0)) for payload in payloads),
            "coord_origin": str(payloads[0].get("coord_origin") or ""),
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def build_heading_blocks(blocks: pd.DataFrame | None) -> list[dict[str, Any]]:
    if blocks is None or blocks.empty:
        return []
    return sorted(
        [
            {
                "page": item.get("page"),
                "heading_path": str(item.get("heading_path") or "").strip() or None,
                "block_order": int(item.get("block_order") or 0),
                "block_type": str(item.get("block_type") or "").strip(),
                "bbox": item.get("bbox"),
            }
            for item in blocks.to_dict(orient="records")
            if str(item.get("heading_path") or "").strip()
        ],
        key=lambda item: (item["page"] is None, item["page"], item["block_order"]),
    )


def build_figure_caption_blocks(blocks: pd.DataFrame | None) -> list[dict[str, Any]]:
    return _build_caption_blocks(blocks, "figure_caption")


def build_table_caption_blocks(blocks: pd.DataFrame | None) -> list[dict[str, Any]]:
    return _build_caption_blocks(blocks, "table_caption")


def find_nearest_caption_block(
    *,
    page: int | None,
    target_bbox: str | None,
    caption_blocks: list[dict[str, Any]],
    used_block_ids: set[str],
) -> dict[str, Any] | None:
    normalized_page = safe_int(page)
    candidates = [
        item
        for item in caption_blocks
        if item.get("block_id")
        and item["block_id"] not in used_block_ids
        and (normalized_page is None or safe_int(item.get("page")) == normalized_page)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            _caption_distance_score(target_bbox, item.get("bbox")),
            int(item.get("block_order") or 0),
        ),
    )


def resolve_heading_path_for_page(
    page: int | None,
    heading_blocks: list[dict[str, Any]],
) -> str | None:
    if not heading_blocks:
        return None
    normalized_page = safe_int(page)
    eligible = [
        item
        for item in heading_blocks
        if item.get("heading_path")
        and (
            normalized_page is None
            or safe_int(item.get("page")) is None
            or safe_int(item.get("page")) <= normalized_page
        )
    ]
    if not eligible:
        return heading_blocks[-1].get("heading_path")
    return eligible[-1].get("heading_path")


def resolve_heading_path_for_target(
    *,
    page: int | None,
    target_bbox: Any,
    heading_blocks: list[dict[str, Any]],
) -> str | None:
    target = load_bbox_payload(target_bbox)
    normalized_page = safe_int(page)
    if target is None or normalized_page is None:
        return resolve_heading_path_for_page(page, heading_blocks)

    candidates = []
    for item in heading_blocks:
        if item.get("block_type") != "heading":
            continue
        if safe_int(item.get("page")) != normalized_page:
            continue
        if not item.get("heading_path"):
            continue
        heading = load_bbox_payload(item.get("bbox"))
        if heading is None:
            continue
        distance = _heading_above_distance(target, heading)
        if distance is None:
            continue
        candidates.append((distance, -(int(item.get("block_order") or 0)), item))

    if not candidates:
        return resolve_heading_path_for_page(page, heading_blocks)
    return min(candidates, key=lambda item: (item[0], item[1]))[2].get("heading_path")


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_bbox_payload(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return json.loads(text)
    if isinstance(value, dict):
        return value
    return {
        "l": float(getattr(value, "l", 0.0)),
        "t": float(getattr(value, "t", 0.0)),
        "r": float(getattr(value, "r", 0.0)),
        "b": float(getattr(value, "b", 0.0)),
        "coord_origin": str(getattr(getattr(value, "coord_origin", None), "value", None) or ""),
    }


def normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    return text or None


def normalize_label(value: Any) -> str | None:
    if value is None:
        return None
    normalized = getattr(value, "value", value)
    return normalize_optional_text(normalized)


def _build_caption_blocks(blocks: pd.DataFrame | None, block_type: str) -> list[dict[str, Any]]:
    if blocks is None or blocks.empty:
        return []
    rows = []
    for item in blocks.to_dict(orient="records"):
        if str(item.get("block_type") or "").strip() != block_type:
            continue
        rows.append(
            {
                "block_id": str(item.get("block_id") or ""),
                "text": str(item.get("text") or "").strip(),
                "page": safe_int(item.get("page")),
                "bbox": item.get("bbox"),
                "block_order": int(item.get("block_order") or 0),
            }
        )
    return rows


def _caption_distance_score(figure_bbox: Any, caption_bbox: Any) -> float:
    figure = load_bbox_payload(figure_bbox)
    caption = load_bbox_payload(caption_bbox)
    if figure is None or caption is None:
        return float("inf")
    return _bbox_vertical_gap(figure, caption)


def _heading_above_distance(
    target: dict[str, Any],
    heading: dict[str, Any],
) -> float | None:
    if _uses_top_left_origin(target, heading):
        distance = float(target.get("t", 0.0)) - float(heading.get("b", 0.0))
    else:
        distance = float(heading.get("b", 0.0)) - float(target.get("t", 0.0))
    return distance if distance >= 0 else None


def _bbox_vertical_gap(first: dict[str, Any], second: dict[str, Any]) -> float:
    if _uses_top_left_origin(first, second):
        first_top = min(float(first.get("t", 0.0)), float(first.get("b", 0.0)))
        first_bottom = max(float(first.get("t", 0.0)), float(first.get("b", 0.0)))
        second_top = min(float(second.get("t", 0.0)), float(second.get("b", 0.0)))
        second_bottom = max(float(second.get("t", 0.0)), float(second.get("b", 0.0)))
    else:
        first_top = max(float(first.get("t", 0.0)), float(first.get("b", 0.0)))
        first_bottom = min(float(first.get("t", 0.0)), float(first.get("b", 0.0)))
        second_top = max(float(second.get("t", 0.0)), float(second.get("b", 0.0)))
        second_bottom = min(float(second.get("t", 0.0)), float(second.get("b", 0.0)))

    if _uses_top_left_origin(first, second):
        if first_bottom < second_top:
            return second_top - first_bottom
        if second_bottom < first_top:
            return first_top - second_bottom
    else:
        if first_bottom > second_top:
            return first_bottom - second_top
        if second_bottom > first_top:
            return second_bottom - first_top
    return 0.0


def _uses_top_left_origin(*payloads: dict[str, Any]) -> bool:
    return any("top" in str(payload.get("coord_origin") or "").lower() for payload in payloads)
