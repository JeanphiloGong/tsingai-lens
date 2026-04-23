# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Utility functions for the Source runtime."""

from infra.source.runtime.cache.memory_pipeline_cache import InMemoryCache
from infra.source.runtime.cache.pipeline_cache import PipelineCache
from infra.source.runtime.callbacks.noop_workflow_callbacks import NoopWorkflowCallbacks
from infra.source.runtime.callbacks.workflow_callbacks import WorkflowCallbacks
from infra.source.runtime.callbacks.workflow_callbacks_manager import (
    WorkflowCallbacksManager,
)
from infra.source.runtime.storage.memory_pipeline_storage import MemoryPipelineStorage
from infra.source.runtime.storage.pipeline_storage import PipelineStorage
from infra.source.runtime.typing.context import PipelineRunContext
from infra.source.runtime.typing.state import PipelineState
from infra.source.runtime.typing.stats import PipelineRunStats


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
