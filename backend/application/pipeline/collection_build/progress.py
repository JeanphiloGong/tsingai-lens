from __future__ import annotations

from typing import Any

from application.pipeline.collection_build.definitions import CollectionBuildNodeDefinition


def build_progress_detail(
    definition: CollectionBuildNodeDefinition,
    *,
    phase: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    return {
        "phase": phase or definition.node_id,
        "unit": "steps",
        "message": message or definition.message,
    }
