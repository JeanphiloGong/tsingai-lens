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


def collect_node_errors(node_states: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for node_id, state in node_states.items():
        for error in state.get("errors", []):
            errors.append(f"{node_id}: {error}")
    return errors


def collect_node_warnings(node_states: dict[str, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for node_id, state in node_states.items():
        for warning in state.get("warnings", []):
            warnings.append(f"{node_id}: {warning}")
    return warnings
