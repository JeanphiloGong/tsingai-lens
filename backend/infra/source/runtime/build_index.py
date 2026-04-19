"""
Indexing API for GraphRAG.

WARNING: This API is under development and may undergo changes in future releases.
Backwards compatibility is not guaranteed at this time.
"""

import logging
from typing import Any

import pandas as pd

import infra.source.runtime.workflows as _source_runtime_workflows
from retrieval.callbacks.noop_workflow_callbacks import NoopWorkflowCallbacks
from retrieval.callbacks.workflow_callbacks import WorkflowCallbacks
from infra.source.config.pipeline_mode import IndexingMethod
from infra.source.config.source_runtime_config import GraphRagConfig
from infra.source.runtime.run_pipeline import run_pipeline
from infra.source.runtime.run_context import create_callback_chain
from infra.source.runtime.typing.pipeline_run_result import PipelineRunResult
from infra.source.runtime.workflows.factory import PipelineFactory
from retrieval.logger.standard_logging import init_loggers

logger = logging.getLogger(__name__)
_ = _source_runtime_workflows


def _summarize_workflow_result(result: Any) -> str:
    if isinstance(result, dict):
        keys = sorted(str(key) for key in result.keys())
        preview = ", ".join(keys[:6])
        suffix = "" if len(keys) <= 6 else ", ..."
        return f"dict[{len(keys)}]: {preview}{suffix}"
    if isinstance(result, list):
        return f"list[{len(result)}]"
    return type(result).__name__


async def build_index(
    config: GraphRagConfig,
    method: IndexingMethod | str = IndexingMethod.Standard,
    memory_profile: bool = False,
    callbacks: list[WorkflowCallbacks] | None = None,
    additional_context: dict[str, Any] | None = None,
    verbose: bool = False,
    input_documents: pd.DataFrame | None = None,
) -> list[PipelineRunResult]:
    """Run the pipeline with the given configuration.

    Parameters
    ----------
    config : GraphRagConfig
        The configuration.
    method : IndexingMethod default=IndexingMethod.Standard
        Styling of indexing to perform (full LLM, NLP + LLM, etc.).
    memory_profile : bool
        Whether to enable memory profiling.
    callbacks : list[WorkflowCallbacks] | None default=None
        A list of callbacks to register.
    additional_context : dict[str, Any] | None default=None
        Additional context to pass to the pipeline run. This can be accessed in the pipeline state under the 'additional_context' key.
    input_documents : pd.DataFrame | None default=None.
        Override document loading and parsing and supply your own dataframe of documents to index.

    Returns
    -------
    list[PipelineRunResult]
        The list of pipeline run results
    """
    init_loggers(config=config, verbose=verbose)

    # Create callbacks for pipeline lifecycle events if provided
    workflow_callbacks = (
        create_callback_chain(callbacks) if callbacks else NoopWorkflowCallbacks()
    )

    outputs: list[PipelineRunResult] = []

    if memory_profile:
        logger.warning("New pipeline does not yet support memory profiling.")

    logger.info("Initializing indexing pipeline...")
    pipeline = PipelineFactory.create_pipeline(config, method)

    workflow_callbacks.pipeline_start(pipeline.names())

    async for output in run_pipeline(
        pipeline,
        config,
        callbacks=workflow_callbacks,
        additional_context=additional_context,
        input_documents=input_documents,
    ):
        outputs.append(output)
        if output.errors and len(output.errors) > 0:
            logger.error("Workflow %s completed with errors", output.workflow)
        else:
            logger.info("Workflow %s completed successfully", output.workflow)
        logger.debug(
            "Workflow %s result summary: %s",
            output.workflow,
            _summarize_workflow_result(output.result),
        )

    workflow_callbacks.pipeline_end(outputs)
    return outputs
