"""A module containing run_workflow method definition."""

import logging

import pandas as pd

from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.runtime.input import create_input
from infra.source.runtime.storage.pipeline_storage import PipelineStorage
from infra.source.runtime.storage.table_io import write_table_to_storage
from infra.source.runtime.typing.context import PipelineRunContext
from infra.source.runtime.typing.workflow import WorkflowFunctionOutput

logger = logging.getLogger(__name__)


async def run_workflow(
    config: SourceRuntimeConfig,
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
    config: object, storage: PipelineStorage
) -> pd.DataFrame:
    """Load and parse input documents into a standard format."""
    return await create_input(config, storage)
