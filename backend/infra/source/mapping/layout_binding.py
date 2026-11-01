from __future__ import annotations

import math
from typing import Any

from infra.source.mapping.values import normalize_optional_text


def first_page(provenance: Any) -> int | None:
    if not provenance:
        return None
    first = provenance[0]
    page_no = getattr(first, "page_no", None)
    try:
        page = float(page_no) if page_no is not None else 0.0
    except (TypeError, ValueError):
        return None
    if not math.isfinite(page) or page <= 0 or not page.is_integer():
        return None
    return int(page)


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
