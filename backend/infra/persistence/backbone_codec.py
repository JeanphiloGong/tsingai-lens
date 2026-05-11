from __future__ import annotations

import ast
import json
import math
from typing import Any


def normalize_backbone_value(value: Any) -> Any:
    """Normalize serialized or table-shaped values into stable Python objects."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {
            str(key): normalize_backbone_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_backbone_value(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_backbone_value(item) for item in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        converted = value.tolist()
        if converted is not value:
            return normalize_backbone_value(converted)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if (text.startswith("{") and text.endswith("}")) or (
            text.startswith("[") and text.endswith("]")
        ):
            for parser in (json.loads, ast.literal_eval):
                try:
                    return normalize_backbone_value(parser(text))
                except (ValueError, SyntaxError, json.JSONDecodeError, TypeError):
                    continue
        return text
    if isinstance(value, float) and math.isnan(value):
        return None
    return value
