"""A module containing run_workflow method definition."""

import logging

import pandas as pd

from retrieval.config.models.graph_rag_config import GraphRagConfig
from retrieval.config.models.input_config import InputConfig
from retrieval.index.input.factory import create_input
from retrieval.index.typing.context import PipelineRunContext
from retrieval.index.typing.workflow import WorkflowFunctionOutput
from retrieval.storage.pipeline_storage import PipelineStorage
from retrieval.utils.storage import write_table_to_storage

logger = logging.getLogger(__name__)


async def run_workflow(
    config: GraphRagConfig,
    context: PipelineRunContext,
) -> WorkflowFunctionOutput:
    """Load and parse input documents into a standard format."""
    output = await load_input_documents(
        config.input,
        context.input_storage,
    )

    logger.info("Final # of rows loaded: %s", len(output))
    context.stats.num_documents = len(output)

    await write_table_to_storage(output, "documents", context.output_storage)

    return WorkflowFunctionOutput(result=output)


async def load_input_documents(
    config: InputConfig, storage: PipelineStorage
) -> pd.DataFrame:
    """Load and parse input documents into a standard format."""
    return await create_input(config, storage)
