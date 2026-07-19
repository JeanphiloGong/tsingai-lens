from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CollectionBuildContext:
    task_id: str
    build_id: str
    collection_id: str
    task_service: Any
    collection_service: Any
    artifact_registry_service: Any
    source_artifact_repository: Any
    config: Any | None = None
    output_dir: Path | None = None
    method: Any | None = None
    verbose: bool = False
    additional_context: dict[str, Any] | None = None
    services: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
