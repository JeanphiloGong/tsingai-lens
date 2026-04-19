# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

# isort: skip_file
"""A module containing the 'PipelineRunContext' models."""

from dataclasses import dataclass

from infra.source.runtime.cache.pipeline_cache import PipelineCache
from infra.source.runtime.callbacks.workflow_callbacks import WorkflowCallbacks
from infra.source.runtime.storage.pipeline_storage import PipelineStorage
from infra.source.runtime.typing.state import PipelineState
from infra.source.runtime.typing.stats import PipelineRunStats


@dataclass
class PipelineRunContext:
    """Provides the context for the current pipeline run."""

    stats: PipelineRunStats
    input_storage: PipelineStorage
    "Storage for input documents."
    output_storage: PipelineStorage
    "Long-term storage for pipeline verbs to use. Items written here will be written to the storage provider."
    cache: PipelineCache
    "Cache instance for reading previous LLM responses."
    callbacks: WorkflowCallbacks
    "Callbacks to be called during the pipeline run."
    state: PipelineState
    "Arbitrary property bag for runtime state, persistent pre-computes, or experimental features."
