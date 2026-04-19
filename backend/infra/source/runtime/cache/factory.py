# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Cache creation for the active Source runtime."""

from __future__ import annotations

from pathlib import Path

from infra.source.config.source_runtime_config import CacheConfig
from infra.source.runtime.cache.json_pipeline_cache import JsonPipelineCache
from infra.source.runtime.cache.memory_pipeline_cache import InMemoryCache
from infra.source.runtime.cache.noop_pipeline_cache import NoopPipelineCache
from infra.source.runtime.cache.pipeline_cache import PipelineCache
from infra.source.runtime.storage.file_pipeline_storage import FilePipelineStorage


def create_cache_from_config(config: CacheConfig, root_dir: str) -> PipelineCache:
    """Create a cache implementation from Source config."""
    cache_type = str(getattr(config.type, "value", config.type))

    if cache_type == "none":
        return NoopPipelineCache()
    if cache_type == "memory":
        return InMemoryCache()
    if cache_type == "file":
        base_dir = str((Path(root_dir) / config.base_dir).resolve())
        storage = FilePipelineStorage(base_dir=base_dir)
        return JsonPipelineCache(storage)
    raise ValueError(f"Unsupported source cache type: {cache_type}")
