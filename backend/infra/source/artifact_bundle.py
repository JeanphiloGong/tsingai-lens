from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Mapping

import pandas as pd

from domain.source import SourceDocument, source_documents_from_records

logger = logging.getLogger(__name__)

_ARTIFACT_ID_FIELDS = (
    "cell_id",
    "row_id",
    "figure_id",
    "block_id",
    "table_id",
    "text_unit_id",
    "id",
    "document_id",
)


@dataclass(frozen=True)
class SourceArtifactBundle:
    documents: pd.DataFrame
    text_units: pd.DataFrame
    blocks: pd.DataFrame
    figures: pd.DataFrame
    tables: pd.DataFrame
    table_rows: pd.DataFrame
    table_cells: pd.DataFrame
    figure_assets: dict[str, bytes]

    def to_documents(self) -> tuple[SourceDocument, ...]:
        return source_documents_from_records(
            documents=_records(self.documents, "documents"),
            text_units=_records(self.text_units, "text_units"),
            blocks=_records(self.blocks, "blocks"),
            figures=_records(self.figures, "figures"),
            tables=_records(self.tables, "tables"),
            table_rows=_records(self.table_rows, "table_rows"),
            table_cells=_records(self.table_cells, "table_cells"),
        )


def _records(frame: pd.DataFrame, artifact_kind: str) -> list[dict]:
    if frame is None or frame.empty:
        return []
    records = frame.to_dict(orient="records")
    sanitized_records: list[dict] = []
    for record in records:
        sanitized, removed_count = _remove_nul(record)
        sanitized_record = dict(sanitized)
        sanitized_records.append(sanitized_record)
        if removed_count:
            artifact_id = next(
                (
                    str(sanitized_record[field])
                    for field in _ARTIFACT_ID_FIELDS
                    if sanitized_record.get(field) not in (None, "")
                ),
                "unknown",
            )
            logger.warning(
                "Removed NUL characters from Source artifact "
                "artifact_kind=%s artifact_id=%s removed_count=%s",
                artifact_kind,
                artifact_id,
                removed_count,
            )
    return sanitized_records


def _remove_nul(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        count = value.count("\x00")
        return value.replace("\x00", ""), count
    if isinstance(value, Mapping):
        cleaned: dict[Any, Any] = {}
        removed_count = 0
        for key, item in value.items():
            cleaned_key, key_count = _remove_nul(key)
            cleaned_item, item_count = _remove_nul(item)
            cleaned[cleaned_key] = cleaned_item
            removed_count += key_count + item_count
        return cleaned, removed_count
    if isinstance(value, list):
        cleaned_items = []
        removed_count = 0
        for item in value:
            cleaned_item, item_count = _remove_nul(item)
            cleaned_items.append(cleaned_item)
            removed_count += item_count
        return cleaned_items, removed_count
    if isinstance(value, tuple):
        cleaned_items = []
        removed_count = 0
        for item in value:
            cleaned_item, item_count = _remove_nul(item)
            cleaned_items.append(cleaned_item)
            removed_count += item_count
        return tuple(cleaned_items), removed_count
    return value, 0
