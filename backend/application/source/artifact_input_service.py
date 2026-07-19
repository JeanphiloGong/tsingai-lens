from __future__ import annotations

import ast
import math
from typing import Any, Iterable, Mapping

from domain.ports import SourceArtifactRepository, SourceReferenceRepository
from domain.source import SourceArtifactSet, SourceDocumentTree, build_source_document_tree


SourceRecord = dict[str, Any]


def load_collection_inputs(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
    *,
    build_id: str | None = None,
) -> tuple[tuple[SourceRecord, ...], tuple[SourceRecord, ...] | None]:
    artifacts = _load_source_artifacts(
        collection_id, source_artifact_repository, build_id=build_id
    )
    documents = _records(document.to_record() for document in artifacts.documents)
    text_units = _records(text_unit.to_record() for text_unit in artifacts.text_units)
    return documents, text_units or None


def load_blocks_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
    *,
    build_id: str | None = None,
) -> tuple[SourceRecord, ...]:
    artifacts = _load_source_artifacts(
        collection_id, source_artifact_repository, build_id=build_id
    )
    return _records(block.to_record() for block in artifacts.blocks)


def load_table_rows_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
    *,
    build_id: str | None = None,
) -> tuple[SourceRecord, ...]:
    artifacts = _load_source_artifacts(
        collection_id, source_artifact_repository, build_id=build_id
    )
    return _records(row.to_record() for row in artifacts.table_rows)


def load_table_cells_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
    *,
    build_id: str | None = None,
) -> tuple[SourceRecord, ...]:
    artifacts = _load_source_artifacts(
        collection_id, source_artifact_repository, build_id=build_id
    )
    return _records(cell.to_record() for cell in artifacts.table_cells)


def load_figures_artifact(
    collection_id: str,
    source_reference_repository: SourceReferenceRepository,
) -> tuple[SourceRecord, ...]:
    return _records(
        figure.to_record()
        for figure in source_reference_repository.list_figures(collection_id)
    )


def load_tables_artifact(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
    *,
    build_id: str | None = None,
) -> tuple[SourceRecord, ...]:
    artifacts = _load_source_artifacts(
        collection_id, source_artifact_repository, build_id=build_id
    )
    return _records(table.to_record() for table in artifacts.tables)


def load_document_tree(
    collection_id: str,
    document_id: str,
    source_artifact_repository: SourceArtifactRepository,
    source_reference_repository: SourceReferenceRepository,
    *,
    build_id: str | None = None,
) -> SourceDocumentTree:
    artifacts = _load_source_artifacts(
        collection_id, source_artifact_repository, build_id=build_id
    )
    document = next(
        (item for item in artifacts.documents if item.document_id == document_id),
        None,
    )
    if document is None:
        raise FileNotFoundError(
            f"source document not found: {collection_id}/{document_id}"
        )
    tree = build_source_document_tree(
        collection_id=collection_id,
        document=document,
        blocks=(item for item in artifacts.blocks if item.document_id == document_id),
        tables=(item for item in artifacts.tables if item.document_id == document_id),
        figures=source_reference_repository.list_figures(collection_id, document_id),
        references=source_reference_repository.read_collection_references(collection_id),
    )
    return tree


def _load_source_artifacts(
    collection_id: str,
    source_artifact_repository: SourceArtifactRepository,
    *,
    build_id: str | None = None,
) -> SourceArtifactSet:
    artifacts = (
        source_artifact_repository.read_collection_artifacts(
            collection_id,
            build_id=build_id,
        )
        if build_id is not None
        else source_artifact_repository.read_collection_artifacts(collection_id)
    )
    if not artifacts.documents:
        raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
    return artifacts


def _records(records: Iterable[Mapping[str, Any]]) -> tuple[SourceRecord, ...]:
    return tuple(dict(record) for record in records)


def build_document_records(
    documents: Iterable[Mapping[str, Any]],
    text_units: Iterable[Mapping[str, Any]] | None = None,
) -> tuple[SourceRecord, ...]:
    document_rows = [dict(row) for row in documents]
    if not document_rows:
        return ()
    if not any("id" in row for row in document_rows):
        raise ValueError("documents missing required 'id' field")
    if not any("text" in row for row in document_rows) and text_units is None:
        raise ValueError("documents missing 'text' and no text_units fallback provided")

    text_unit_rows = [dict(row) for row in text_units or ()]
    text_unit_ids_by_doc: dict[str, list[str]] = {}
    if text_unit_rows and all({"id", "text"}.issubset(row) for row in text_unit_rows):
        for row in text_unit_rows:
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
        if any(column in row for row in document_rows)
    ]

    rows: list[SourceRecord] = []
    for row in document_rows:
        paper_id = str(row.get("id"))
        text = str(row.get("text") or "").strip()
        if not text and text_unit_rows:
            text = _join_text_units_for_document(text_unit_rows, paper_id)
        payload: SourceRecord = {
            "paper_id": paper_id,
            "title": _coerce_optional_text(row.get("title")) or paper_id,
            "text": text,
            "text_unit_ids": text_unit_ids_by_doc.get(paper_id, []),
        }
        for column in passthrough_columns:
            payload[column] = row.get(column)
        rows.append(payload)

    return tuple(rows)


def _join_text_units_for_document(
    text_units: Iterable[Mapping[str, Any]],
    paper_id: str,
) -> str:
    matched: list[str] = []
    for row in text_units:
        if paper_id not in {str(item) for item in _listify(row.get("document_ids"))}:
            continue
        text = str(row.get("text") or "").strip()
        if text:
            matched.append(text)
    return "\n".join(matched)


def _coerce_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, float) and math.isnan(value):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
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
    return [value]
