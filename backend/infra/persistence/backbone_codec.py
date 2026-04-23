from __future__ import annotations

import ast
import json
from typing import Any

import pandas as pd


def normalize_backbone_value(value: Any) -> Any:
    """Normalize parquet- and pandas-backed values into stable Python objects."""
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
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def prepare_frame_for_storage(
    frame: pd.DataFrame,
    json_columns: tuple[str, ...],
) -> pd.DataFrame:
    """Encode nested artifact columns as JSON strings before parquet writes."""
    encoded = frame.copy()
    for column in json_columns:
        if column in encoded.columns:
            encoded[column] = encoded[column].apply(_encode_json_value)
    return encoded


def restore_frame_from_storage(
    frame: pd.DataFrame,
    json_columns: tuple[str, ...],
) -> pd.DataFrame:
    """Decode nested artifact columns back into stable Python objects."""
    restored = frame.copy()
    for column in json_columns:
        if column in restored.columns:
            restored[column] = restored[column].apply(_decode_json_value)
    return restored


def _encode_json_value(value: Any) -> str:
    normalized = normalize_backbone_value(value)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def _decode_json_value(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for parser in (json.loads, ast.literal_eval):
            try:
                return normalize_backbone_value(parser(text))
            except (ValueError, SyntaxError, json.JSONDecodeError, TypeError):
                continue
    return normalize_backbone_value(value)
