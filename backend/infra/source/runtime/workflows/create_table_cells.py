# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Persist Source-owned table-cell evidence."""

import logging

import pandas as pd

from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.contracts.artifact_schemas import TABLE_CELLS_FINAL_COLUMNS
from infra.source.runtime.source_evidence import build_table_cells
from infra.source.runtime.storage.table_io import (
    load_table_from_storage,
    write_table_to_storage,
)
from infra.source.runtime.typing.context import PipelineRunContext
from infra.source.runtime.typing.workflow import WorkflowFunctionOutput

logger = logging.getLogger(__name__)


async def run_workflow(
    _config: SourceRuntimeConfig,
    context: PipelineRunContext,
) -> WorkflowFunctionOutput:
    logger.info("Workflow started: create_table_cells")
    documents = await load_table_from_storage("documents", context.output_storage)
    text_units = await load_table_from_storage("text_units", context.output_storage)
    output = create_table_cells(documents, text_units)
    await write_table_to_storage(output, "table_cells", context.output_storage)
    logger.info("Workflow completed: create_table_cells")
    return WorkflowFunctionOutput(result=output)


def create_table_cells(
    documents: pd.DataFrame,
    text_units: pd.DataFrame,
) -> pd.DataFrame:
    table_cells = build_table_cells(documents, text_units)
    normalized = table_cells.copy()
    for column in ("cell_id", "table_id", "row_index", "col_index", "cell_text", "header_path", "page", "bbox", "char_range", "unit_hint"):
        if column not in normalized.columns:
            normalized[column] = None
    normalized["id"] = normalized.get("document_id")
    return normalized.loc[:, TABLE_CELLS_FINAL_COLUMNS]
