from __future__ import annotations

from typing import Any

from domain.source import normalize_optional_text


def first_page(provenance: Any) -> int | None:
    if not provenance:
        return None
    first = provenance[0]
    page_no = getattr(first, "page_no", None)
    return int(page_no) if page_no is not None else None


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
