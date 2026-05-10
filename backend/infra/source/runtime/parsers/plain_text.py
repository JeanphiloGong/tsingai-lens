from __future__ import annotations

from typing import Any

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
from infra.source.runtime.parsers.common import (
    build_source_metadata,
    resolve_document_id,
    resolve_document_title,
)
from infra.source.runtime.source_evidence import build_blocks, build_table_rows
from infra.source.runtime.workflows.create_base_text_units import create_base_text_units
from infra.source.runtime.workflows.create_final_documents import create_final_documents
from infra.source.runtime.workflows.create_final_text_units import create_final_text_units
from infra.source.runtime.workflows.create_table_cells import create_table_cells


def build_text_bundle(
    *,
    row: pd.Series,
    text: str,
    config: SourceRuntimeConfig,
    callbacks: Any,
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

    base_text_units = create_base_text_units(
        document_frame,
        callbacks,
        config.chunks.group_by_columns,
        config.chunks.size,
        config.chunks.overlap,
        config.chunks.encoding_model,
        strategy=config.chunks.strategy,
        prepend_metadata=config.chunks.prepend_metadata,
        chunk_size_includes_metadata=config.chunks.chunk_size_includes_metadata,
    )
    final_documents = create_final_documents(document_frame, base_text_units)
    final_text_units = create_final_text_units(base_text_units)
    final_blocks = build_blocks(final_documents, final_text_units)
    final_table_rows = build_table_rows(final_documents, final_text_units)
    final_table_cells = create_table_cells(final_documents, final_text_units)
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
