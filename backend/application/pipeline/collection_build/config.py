from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infra.source.config.pipeline_mode import IndexingMethod
from infra.source.config.source_runtime_config import SourceRuntimeConfig


@dataclass(frozen=True)
class CollectionBuildPipelineConfig:
    source: SourceRuntimeConfig
    mode: IndexingMethod | str
    verbose: bool = False
    source_additional_context: dict[str, Any] | None = None
