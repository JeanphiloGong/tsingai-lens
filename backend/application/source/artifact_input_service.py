from __future__ import annotations

import ast
from typing import Any

import pandas as pd

from domain.source import SourceArtifactSet
from domain.ports import SourceArtifactRepository
from infra.persistence.factory import build_source_artifact_repository
from infra.source.contracts.artifact_schemas import (
    BLOCKS_FINAL_COLUMNS,
    DOCUMENTS_FINAL_COLUMNS,
    FIGURES_FINAL_COLUMNS,
    TABLE_CELLS_FINAL_COLUMNS,
    TABLES_FINAL_COLUMNS,
    TABLE_ROWS_FINAL_COLUMNS,
    TEXT_UNITS_FINAL_COLUMNS,
)


def load_collection_inputs(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    artifacts = _load_source_artifacts(collection_id, source_artifact_repository)
    documents = _records_to_frame(
        (document.to_record() for document in artifacts.documents),
        DOCUMENTS_FINAL_COLUMNS,
    )
    text_units = _records_to_frame(
        (text_unit.to_record() for text_unit in artifacts.text_units),
        TEXT_UNITS_FINAL_COLUMNS,
    )
    return documents, text_units if not text_units.empty else None


def load_blocks_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository | None = None,
) -> pd.DataFrame:
    artifacts = _load_source_artifacts(collection_id, source_artifact_repository)
    return _records_to_frame(
        (block.to_record() for block in artifacts.blocks),
        BLOCKS_FINAL_COLUMNS,
    )


def load_table_rows_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository | None = None,
) -> pd.DataFrame:
    artifacts = _load_source_artifacts(collection_id, source_artifact_repository)
    return _records_to_frame(
        (row.to_record() for row in artifacts.table_rows),
        TABLE_ROWS_FINAL_COLUMNS,
    )


def load_table_cells_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository | None = None,
) -> pd.DataFrame:
    artifacts = _load_source_artifacts(collection_id, source_artifact_repository)
    return _records_to_frame(
        (cell.to_record() for cell in artifacts.table_cells),
        TABLE_CELLS_FINAL_COLUMNS,
    )


def load_figures_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository | None = None,
) -> pd.DataFrame:
    artifacts = _load_source_artifacts(collection_id, source_artifact_repository)
    return _records_to_frame(
        (figure.to_record() for figure in artifacts.figures),
        FIGURES_FINAL_COLUMNS,
    )


def load_tables_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository | None = None,
) -> pd.DataFrame:
    artifacts = _load_source_artifacts(collection_id, source_artifact_repository)
    return _records_to_frame(
        (table.to_record() for table in artifacts.tables),
        TABLES_FINAL_COLUMNS,
    )


def _load_source_artifacts(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository | None = None,
) -> SourceArtifactSet:
    repository = source_artifact_repository or build_source_artifact_repository()
    artifacts = repository.read_collection_artifacts(collection_id)
    if not artifacts.documents:
        raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
    return artifacts


def _records_to_frame(records: Any, columns: list[str]) -> pd.DataFrame:
    rows = list(records)
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def build_document_records(
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if "id" not in documents.columns:
        raise ValueError("documents dataframe missing required 'id' column")
    if "text" not in documents.columns and text_units is None:
        raise ValueError("documents dataframe missing 'text' and no text_units fallback provided")

    text_unit_ids_by_doc: dict[str, list[str]] = {}
    if text_units is not None and {"id", "text"}.issubset(text_units.columns):
        for _, row in text_units.iterrows():
            text_unit_id = str(row.get("id"))
            for doc_id in _listify(row.get("document_ids")):
                text_unit_ids_by_doc.setdefault(str(doc_id), []).append(text_unit_id)

    passthrough_columns = [
        column
        for column in (
            "creation_date",
            "metadata",
            "source_filename",
            "original_filename",
            "stored_filename",
        )
        if column in documents.columns
    ]

    rows: list[dict[str, Any]] = []
    for _, row in documents.iterrows():
        paper_id = str(row.get("id"))
        text = str(row.get("text") or "").strip()
        if not text and text_units is not None:
            text = _join_text_units_for_document(text_units, paper_id)
        payload = {
            "paper_id": paper_id,
            "title": _coerce_optional_text(row.get("title")) or paper_id,
            "text": text,
            "text_unit_ids": text_unit_ids_by_doc.get(paper_id, []),
        }
        for column in passthrough_columns:
            payload[column] = row.get(column)
        rows.append(payload)

    return pd.DataFrame(
        rows,
        columns=["paper_id", "title", "text", "text_unit_ids", *passthrough_columns],
    )


def _join_text_units_for_document(text_units: pd.DataFrame, paper_id: str) -> str:
    matched: list[str] = []
    for _, row in text_units.iterrows():
        if paper_id not in {str(item) for item in _listify(row.get("document_ids"))}:
            continue
        text = str(row.get("text") or "").strip()
        if text:
            matched.append(text)
    return "\n".join(matched)


def _coerce_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        converted = value.tolist()
        if converted is not value:
            return _listify(converted)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                return [text]
            if isinstance(parsed, list):
                return parsed
        return [text]
    if isinstance(value, float) and pd.isna(value):
        return []
    return [value]
