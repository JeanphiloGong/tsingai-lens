# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Run the indexing pipeline."""

import json
import logging
import time
from collections.abc import AsyncIterable
from dataclasses import asdict
from typing import Any

import pandas as pd

from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.runtime.run_context import create_run_context
from infra.source.runtime.storage.factory import create_storage_from_config
from infra.source.runtime.storage.table_io import write_table_to_storage
from infra.source.runtime.typing.context import PipelineRunContext
from infra.source.runtime.typing.pipeline import Pipeline
from infra.source.runtime.typing.pipeline_run_result import PipelineRunResult

logger = logging.getLogger(__name__)


async def run_pipeline(
    pipeline: Pipeline,
    config: SourceRuntimeConfig,
    additional_context: dict[str, Any] | None = None,
    input_documents: pd.DataFrame | None = None,
) -> AsyncIterable[PipelineRunResult]:
    """Run all workflows using a simplified pipeline."""
    input_storage = create_storage_from_config(config.input.storage)
    output_storage = create_storage_from_config(config.output)

    # load existing state in case any workflows are stateful
    state_json = await output_storage.get("context.json")
    state = json.loads(state_json) if state_json else {}

    if additional_context:
        state.setdefault("additional_context", {}).update(additional_context)

    logger.info("Running standard indexing.")

    # if the user passes in a df directly, write directly to storage so we can skip finding/parsing later
    if input_documents is not None:
        await write_table_to_storage(input_documents, "documents", output_storage)
        pipeline.remove("load_input_documents")

    context = create_run_context(
        input_storage=input_storage,
        output_storage=output_storage,
        state=state,
    )

    async for table in _run_pipeline(
        pipeline=pipeline,
        config=config,
        context=context,
    ):
        yield table


async def _run_pipeline(
    pipeline: Pipeline,
    config: SourceRuntimeConfig,
    context: PipelineRunContext,
) -> AsyncIterable[PipelineRunResult]:
    start_time = time.time()

    last_workflow = "<startup>"

    try:
        await _dump_json(context)

        logger.info("Executing pipeline...")
        for name, workflow_function in pipeline.run():
            last_workflow = name
            work_time = time.time()
            result = await workflow_function(config, context)
            yield PipelineRunResult(
                workflow=name, result=result.result, state=context.state, errors=None
            )
            context.stats.workflows[name] = {"overall": time.time() - work_time}
            if result.stop:
                logger.info("Halting pipeline at workflow request")
                break

        context.stats.total_runtime = time.time() - start_time
        logger.info("Indexing pipeline complete.")
        await _dump_json(context)

    except Exception as e:
        logger.exception("error running workflow %s", last_workflow)
        yield PipelineRunResult(
            workflow=last_workflow, result=None, state=context.state, errors=[e]
        )


async def _dump_json(context: PipelineRunContext) -> None:
    """Dump the stats and context state to the storage."""
    await context.output_storage.set(
        "stats.json", json.dumps(asdict(context.stats), indent=4, ensure_ascii=False)
    )
    # Dump context state, excluding additional_context
    temp_context = context.state.pop(
        "additional_context", None
    )  # Remove reference only, as object size is uncertain
    try:
        state_blob = json.dumps(context.state, indent=4, ensure_ascii=False)
    finally:
        if temp_context:
            context.state["additional_context"] = temp_context

    await context.output_storage.set("context.json", state_blob)
