# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Parse plain text into traceable Source artifacts."""

from __future__ import annotations

import ast
from typing import Any, cast

import pandas as pd

from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.contracts.artifact_schemas import (
    BLOCKS_FINAL_COLUMNS,
    DOCUMENTS_FINAL_COLUMNS,
    FIGURES_FINAL_COLUMNS,
    TABLE_CELLS_FINAL_COLUMNS,
    TABLES_FINAL_COLUMNS,
    TABLE_ROWS_FINAL_COLUMNS,
    TEXT_UNITS_FINAL_COLUMNS,
)
from infra.source.runtime.artifact_bundle import SourceArtifactBundle
from infra.source.runtime.chunking import chunk_text
from infra.source.runtime.hashing import gen_sha512_hash
from infra.source.runtime.parsers.common import (
    build_source_metadata,
    resolve_document_id,
    resolve_document_title,
)
from infra.source.runtime.source_evidence import (
    build_blocks,
    build_table_cells,
    build_table_rows,
)

def build_text_bundle(
    *,
    row: pd.Series,
    text: str,
    config: SourceRuntimeConfig,
) -> SourceArtifactBundle:
    document_id = resolve_document_id(row)
    title = resolve_document_title(row)
    metadata = build_source_metadata(row, parser_name="plain_text")
    document_frame = pd.DataFrame(
        [
            {
                "id": document_id,
                "title": title,
                "text": text,
                "creation_date": row.get("creation_date"),
                "metadata": metadata,
            }
        ]
    )

    base_text_units = _chunk_document_text(
        document_id,
        text,
        config.chunks.size,
        config.chunks.overlap,
        config.chunks.encoding_model,
    )
    final_documents = _bind_text_units_to_documents(document_frame, base_text_units)
    final_text_units = _normalize_text_units(base_text_units)
    final_blocks = build_blocks(final_documents, final_text_units)
    final_table_rows = build_table_rows(final_documents, final_text_units)
    final_table_cells = build_table_cells(final_documents, final_text_units).copy()
    final_table_cells["id"] = final_table_cells.get("document_id")
    for column in TABLE_CELLS_FINAL_COLUMNS:
        if column not in final_table_cells.columns:
            final_table_cells[column] = None
    return SourceArtifactBundle(
        documents=final_documents.loc[:, DOCUMENTS_FINAL_COLUMNS],
        text_units=final_text_units.loc[:, TEXT_UNITS_FINAL_COLUMNS],
        blocks=final_blocks.loc[:, BLOCKS_FINAL_COLUMNS],
        figures=pd.DataFrame(columns=FIGURES_FINAL_COLUMNS),
        tables=pd.DataFrame(columns=TABLES_FINAL_COLUMNS),
        table_rows=final_table_rows.loc[:, TABLE_ROWS_FINAL_COLUMNS],
        table_cells=final_table_cells.loc[:, TABLE_CELLS_FINAL_COLUMNS],
        figure_assets={},
    )


def _chunk_document_text(
    document_id: str,
    text: str,
    size: int,
    overlap: int,
    encoding_model: str,
) -> pd.DataFrame:
    """Chunk one plain-text document into traceable Source text units."""
    rows: list[dict[str, Any]] = []
    for chunk in chunk_text(
        text=text,
        size=size,
        overlap=overlap,
        encoding_model=encoding_model,
    ):
        chunk_record = ([document_id], chunk.text_chunk, chunk.n_tokens)
        rows.append(
            {
                "id": gen_sha512_hash({"chunk": chunk_record}, ["chunk"]),
                "document_ids": [document_id],
                "text": chunk.text_chunk,
                "n_tokens": chunk.n_tokens,
            }
        )

    return pd.DataFrame(rows, columns=["id", "text", "document_ids", "n_tokens"])


def _bind_text_units_to_documents(
    documents: pd.DataFrame, text_units: pd.DataFrame
) -> pd.DataFrame:
    """Normalize documents into the minimal Source handoff consumed by Core."""
    exploded = (
        text_units.explode("document_ids")
        .loc[:, ["id", "document_ids", "text"]]
        .rename(
            columns={
                "document_ids": "chunk_doc_id",
                "id": "chunk_id",
                "text": "chunk_text",
            }
        )
    )

    joined = exploded.merge(
        documents,
        left_on="chunk_doc_id",
        right_on="id",
        how="inner",
        copy=False,
    )

    docs_with_text_units = joined.groupby("id", sort=False).agg(
        text_unit_ids=("chunk_id", list)
    )

    rejoined = docs_with_text_units.merge(
        documents,
        on="id",
        how="right",
        copy=False,
    ).reset_index(drop=True)

    rejoined["id"] = rejoined["id"].astype(str)
    rejoined["document_order"] = rejoined.index

    if "creation_date" not in rejoined.columns:
        rejoined["creation_date"] = pd.Series(dtype="object")
    if "metadata" not in rejoined.columns:
        rejoined["metadata"] = pd.Series(dtype="object")

    return rejoined.loc[:, DOCUMENTS_FINAL_COLUMNS]


def _normalize_text_units(
    text_units: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize text units into the minimal Source handoff consumed by Core."""
    normalized = text_units.copy()
    for column in ("id", "text", "document_ids", "n_tokens"):
        if column not in normalized.columns:
            normalized[column] = None

    selected = normalized.loc[:, ["id", "text", "document_ids", "n_tokens"]].copy()
    selected["id"] = selected["id"].astype(str)
    selected["text"] = selected["text"].fillna("").astype(str)
    selected["document_ids"] = selected["document_ids"].apply(_normalize_string_list)
    selected["text_unit_order"] = range(len(selected))

    return selected.loc[:, TEXT_UNITS_FINAL_COLUMNS]


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple | set):
        return [str(item) for item in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        converted = value.tolist()
        if converted is not value:
            return _normalize_string_list(converted)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                return [text]
            return _normalize_string_list(parsed)
        return [text]
    if isinstance(value, float) and pd.isna(value):
        return []
    return [str(value)]
