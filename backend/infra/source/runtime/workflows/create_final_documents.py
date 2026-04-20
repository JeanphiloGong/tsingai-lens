# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""A module containing run_workflow method definition."""

import logging

import pandas as pd

from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.contracts.artifact_schemas import DOCUMENTS_FINAL_COLUMNS
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
    """All the steps to transform final documents."""
    logger.info("Workflow started: create_final_documents")
    documents = await load_table_from_storage("documents", context.output_storage)
    text_units = await load_table_from_storage("text_units", context.output_storage)

    output = create_final_documents(documents, text_units)

    await write_table_to_storage(output, "documents", context.output_storage)

    logger.info("Workflow completed: create_final_documents")
    return WorkflowFunctionOutput(result=output)


def create_final_documents(
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
    rejoined["human_readable_id"] = rejoined.index

    if "creation_date" not in rejoined.columns:
        rejoined["creation_date"] = pd.Series(dtype="object")
    if "metadata" not in rejoined.columns:
        rejoined["metadata"] = pd.Series(dtype="object")

    return rejoined.loc[:, DOCUMENTS_FINAL_COLUMNS]
