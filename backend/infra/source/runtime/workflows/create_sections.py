# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Persist Source-owned section evidence."""

import logging

import pandas as pd

from infra.source.config.source_runtime_config import GraphRagConfig
from infra.source.contracts.artifact_schemas import SECTIONS_FINAL_COLUMNS
from infra.source.runtime.source_evidence import build_sections
from infra.source.runtime.storage.table_io import (
    load_table_from_storage,
    write_table_to_storage,
)
from infra.source.runtime.typing.context import PipelineRunContext
from infra.source.runtime.typing.workflow import WorkflowFunctionOutput

logger = logging.getLogger(__name__)


async def run_workflow(
    _config: GraphRagConfig,
    context: PipelineRunContext,
) -> WorkflowFunctionOutput:
    logger.info("Workflow started: create_sections")
    documents = await load_table_from_storage("documents", context.output_storage)
    text_units = await load_table_from_storage("text_units", context.output_storage)
    output = create_sections(documents, text_units)
    await write_table_to_storage(output, "sections", context.output_storage)
    logger.info("Workflow completed: create_sections")
    return WorkflowFunctionOutput(result=output)


def create_sections(
    documents: pd.DataFrame,
    text_units: pd.DataFrame,
) -> pd.DataFrame:
    sections = build_sections(documents, text_units)
    normalized = sections.copy()
    for column in ("section_id", "title", "section_type", "heading", "text", "order", "text_unit_ids", "page", "char_range", "confidence"):
        if column not in normalized.columns:
            normalized[column] = None
    normalized["id"] = normalized.get("paper_id")
    return normalized.loc[:, SECTIONS_FINAL_COLUMNS]
