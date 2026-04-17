# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""A module containing run_workflow method definition."""

import ast
import logging
from typing import Any

import pandas as pd

from retrieval.data_model.schemas import TEXT_UNITS_FINAL_COLUMNS
from retrieval.config.models.graph_rag_config import GraphRagConfig
from retrieval.index.typing.context import PipelineRunContext
from retrieval.index.typing.workflow import WorkflowFunctionOutput
from retrieval.utils.storage import load_table_from_storage, write_table_to_storage

logger = logging.getLogger(__name__)


async def run_workflow(
    _config: GraphRagConfig,
    context: PipelineRunContext,
) -> WorkflowFunctionOutput:
    """All the steps to transform the text units."""
    logger.info("Workflow started: create_final_text_units")
    text_units = await load_table_from_storage("text_units", context.output_storage)
    output = create_final_text_units(text_units)

    await write_table_to_storage(output, "text_units", context.output_storage)

    logger.info("Workflow completed: create_final_text_units")
    return WorkflowFunctionOutput(result=output)


def create_final_text_units(
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
    selected["human_readable_id"] = range(len(selected))

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
