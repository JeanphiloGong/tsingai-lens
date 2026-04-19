# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Utility functions for the GraphRAG run module."""

from retrieval.cache.memory_pipeline_cache import InMemoryCache
from retrieval.cache.pipeline_cache import PipelineCache
from retrieval.callbacks.noop_workflow_callbacks import NoopWorkflowCallbacks
from retrieval.callbacks.workflow_callbacks import WorkflowCallbacks
from retrieval.callbacks.workflow_callbacks_manager import WorkflowCallbacksManager
from infra.source.runtime.typing.context import PipelineRunContext
from infra.source.runtime.typing.state import PipelineState
from infra.source.runtime.typing.stats import PipelineRunStats
from retrieval.storage.memory_pipeline_storage import MemoryPipelineStorage
from retrieval.storage.pipeline_storage import PipelineStorage


def create_run_context(
    input_storage: PipelineStorage | None = None,
    output_storage: PipelineStorage | None = None,
    cache: PipelineCache | None = None,
    callbacks: WorkflowCallbacks | None = None,
    stats: PipelineRunStats | None = None,
    state: PipelineState | None = None,
) -> PipelineRunContext:
    """Create the run context for the pipeline."""
    return PipelineRunContext(
        input_storage=input_storage or MemoryPipelineStorage(),
        output_storage=output_storage or MemoryPipelineStorage(),
        cache=cache or InMemoryCache(),
        callbacks=callbacks or NoopWorkflowCallbacks(),
        stats=stats or PipelineRunStats(),
        state=state or {},
    )


def create_callback_chain(
    callbacks: list[WorkflowCallbacks] | None,
) -> WorkflowCallbacks:
    """Create a callback manager that encompasses multiple callbacks."""
    manager = WorkflowCallbacksManager()
    for callback in callbacks or []:
        manager.register(callback)
    return manager
