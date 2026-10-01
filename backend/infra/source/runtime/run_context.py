# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Utility functions for the Source runtime."""

from infra.source.runtime.storage.memory_pipeline_storage import MemoryPipelineStorage
from infra.source.runtime.storage.pipeline_storage import PipelineStorage
from infra.source.runtime.typing.context import PipelineRunContext
from infra.source.runtime.typing.state import PipelineState
from infra.source.runtime.typing.stats import PipelineRunStats


def create_run_context(
    input_storage: PipelineStorage | None = None,
    output_storage: PipelineStorage | None = None,
    stats: PipelineRunStats | None = None,
    state: PipelineState | None = None,
) -> PipelineRunContext:
    """Create the run context for the pipeline."""
    return PipelineRunContext(
        input_storage=input_storage or MemoryPipelineStorage(),
        output_storage=output_storage or MemoryPipelineStorage(),
        stats=stats or PipelineRunStats(),
        state=state or {},
    )
