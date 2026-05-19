from __future__ import annotations

from typing import Any

from domain.source import (
    SourceBoundingBox,
    SourceCharRange,
    normalize_optional_text,
)


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
    char_range = SourceCharRange.from_value(charspan)
    return char_range.to_json() if char_range else None


def serialize_prov_bbox(provenance: Any) -> str | None:
    if not provenance:
        return None
    first = provenance[0]
    return serialize_bbox(getattr(first, "bbox", None))


def serialize_bbox(bbox: Any) -> str | None:
    source_bbox = SourceBoundingBox.from_value(bbox)
    return source_bbox.to_json() if source_bbox else None


def first_bbox(provenance: Any) -> Any | None:
    if not provenance:
        return None
    first = provenance[0]
    return getattr(first, "bbox", None)


def normalize_label(value: Any) -> str | None:
    if value is None:
        return None
    normalized = getattr(value, "value", value)
    return normalize_optional_text(normalized)
