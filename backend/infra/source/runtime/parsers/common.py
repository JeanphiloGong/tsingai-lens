from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from infra.source.runtime.hashing import gen_sha512_hash


def resolve_document_id(row: pd.Series) -> str:
    document_id = str(row.get("id") or "").strip()
    if document_id:
        return document_id
    source_path = str(row.get("source_path") or "").strip()
    title = resolve_document_title(row)
    return gen_sha512_hash(
        {
            "source_path": source_path,
            "title": title,
        },
        ["source_path", "title"],
    )


def resolve_document_title(row: pd.Series) -> str:
    title = str(row.get("title") or "").strip()
    if title:
        return title
    source_path = str(row.get("source_path") or "").strip()
    if source_path:
        return Path(source_path).name
    return str(row.get("id") or "document")


def build_source_metadata(row: pd.Series, *, parser_name: str) -> dict[str, Any]:
    metadata = row.get("metadata")
    payload = dict(metadata) if isinstance(metadata, dict) else {}
    source_path = str(row.get("source_path") or "").strip()
    source_type = str(row.get("source_type") or Path(source_path).suffix.lstrip(".")).strip()
    if source_path:
        payload["source_path"] = source_path
    if source_type:
        payload["source_type"] = source_type
    payload["source_parser"] = parser_name
    return payload
