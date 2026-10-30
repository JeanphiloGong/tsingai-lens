"""Parse optional values from parser and DataFrame inputs."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def normalize_optional_text(value: Any) -> str | None:
    if _is_missing_value(value):
        return None
    text = str(value).strip()
    return text or None



def safe_int(value: Any) -> int | None:
    if _is_missing_value(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None



def first_non_null(values: Iterable[Any]) -> Any:
    for value in values:
        if value is None:
            continue
        if _is_missing_value(value):
            continue
        return value
    return None



def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False
