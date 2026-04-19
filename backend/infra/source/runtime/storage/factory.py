# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Storage creation for the active Source runtime."""

from __future__ import annotations

from infra.source.config.source_runtime_config import StorageConfig
from infra.source.runtime.storage.file_pipeline_storage import FilePipelineStorage
from infra.source.runtime.storage.memory_pipeline_storage import MemoryPipelineStorage
from infra.source.runtime.storage.pipeline_storage import PipelineStorage


def create_storage_from_config(config: StorageConfig) -> PipelineStorage:
    """Create a storage implementation from Source config."""
    storage_type = str(getattr(config.type, "value", config.type))
    config_dict = config.model_dump()

    if storage_type == "file":
        return FilePipelineStorage(**config_dict)
    if storage_type == "memory":
        return MemoryPipelineStorage()
    raise ValueError(f"Unsupported source storage type: {storage_type}")
