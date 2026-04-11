from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import HTTPException


_DOCUMENT_FILE = "documents.parquet"


def load_document_title_map(base_dir: Path) -> dict[str, str]:
    path = base_dir / _DOCUMENT_FILE
    if not path.is_file():
        return {}

    try:
        documents = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"无法读取 documents.parquet: {exc}") from exc

    if "id" not in documents.columns:
        return {}

    title_map: dict[str, str] = {}
    for _, row in documents.iterrows():
        paper_id = str(row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if paper_id and title:
            title_map[paper_id] = title

    return title_map
