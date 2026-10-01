# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Parse plain text into traceable Source artifacts."""

from __future__ import annotations

import ast
import json
import logging
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
from infra.source.runtime.chunking import chunk_text, get_encoding_fn
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

logger = logging.getLogger(__name__)


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
        document_frame,
        config.chunks.group_by_columns,
        config.chunks.size,
        config.chunks.overlap,
        config.chunks.encoding_model,
        strategy=config.chunks.strategy,
        prepend_metadata=config.chunks.prepend_metadata,
        chunk_size_includes_metadata=config.chunks.chunk_size_includes_metadata,
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
    documents: pd.DataFrame,
    group_by_columns: list[str],
    size: int,
    overlap: int,
    encoding_model: str,
    strategy: Any,
    prepend_metadata: bool = False,
    chunk_size_includes_metadata: bool = False,
) -> pd.DataFrame:
    """Chunk document text while retaining source IDs and metadata token budgets."""
    sort = documents.sort_values(by=["id"], ascending=[True])

    sort["text_with_ids"] = list(
        zip(*[sort[col] for col in ["id", "text"]], strict=True)
    )

    agg_dict = {"text_with_ids": list}
    if "metadata" in documents:
        agg_dict["metadata"] = "first"  # type: ignore

    aggregated = (
        (
            sort.groupby(group_by_columns, sort=False)
            if len(group_by_columns) > 0
            else sort.groupby(lambda _x: True)
        )
        .agg(agg_dict)
        .reset_index()
    )
    aggregated.rename(columns={"text_with_ids": "texts"}, inplace=True)

    def chunker(row: pd.Series) -> Any:
        line_delimiter = ".\n"
        metadata_str = ""
        metadata_tokens = 0

        if prepend_metadata and "metadata" in row:
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            if isinstance(metadata, dict):
                metadata_str = (
                    line_delimiter.join(f"{k}: {v}" for k, v in metadata.items())
                    + line_delimiter
                )

            if chunk_size_includes_metadata:
                encode, _ = get_encoding_fn(encoding_model)
                metadata_tokens = len(encode(metadata_str))
                if metadata_tokens >= size:
                    message = "Metadata tokens exceeds the maximum tokens per chunk. Please increase the tokens per chunk."
                    raise ValueError(message)

        chunked = chunk_text(
            pd.DataFrame([row]).reset_index(drop=True),
            column="texts",
            size=size - metadata_tokens,
            overlap=overlap,
            encoding_model=encoding_model,
            strategy=strategy,
        )[0]

        if prepend_metadata:
            for index, chunk in enumerate(chunked):
                if isinstance(chunk, str):
                    chunked[index] = metadata_str + chunk
                else:
                    chunked[index] = (
                        (chunk[0], metadata_str + chunk[1], chunk[2]) if chunk else None
                    )

        row["chunks"] = chunked
        return row

    # Track progress of row-wise apply operation
    total_rows = len(aggregated)
    logger.info("Starting chunking process for %d documents", total_rows)

    def chunker_with_logging(row: pd.Series, row_index: int) -> Any:
        """Add logging to chunker execution."""
        result = chunker(row)
        logger.info("chunker progress:  %d/%d", row_index + 1, total_rows)
        return result

    aggregated = aggregated.apply(
        lambda row: chunker_with_logging(row, row.name), axis=1
    )

    aggregated = cast("pd.DataFrame", aggregated[[*group_by_columns, "chunks"]])
    aggregated = aggregated.explode("chunks")
    aggregated.rename(
        columns={
            "chunks": "chunk",
        },
        inplace=True,
    )
    aggregated["id"] = aggregated.apply(
        lambda row: gen_sha512_hash(row, ["chunk"]), axis=1
    )
    aggregated[["document_ids", "chunk", "n_tokens"]] = pd.DataFrame(
        aggregated["chunk"].tolist(), index=aggregated.index
    )
    # rename for downstream consumption
    aggregated.rename(columns={"chunk": "text"}, inplace=True)

    return cast(
        "pd.DataFrame", aggregated[aggregated["text"].notna()].reset_index(drop=True)
    )


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
