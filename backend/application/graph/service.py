from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from application.collections.service import CollectionService
from application.workspace.artifact_registry_service import ArtifactRegistryService
from infra.graphrag.graphml_export import (
    load_graph_payload as load_graph_payload_from_storage,
    to_graphml as render_graphml,
)


artifact_registry_service = ArtifactRegistryService()
collection_service = CollectionService()


def resolve_collection_output_dir(collection_id: str) -> Path:
    try:
        payload = artifact_registry_service.get(collection_id)
        output_path = payload.get("output_path")
        if output_path:
            base_dir = Path(str(output_path)).expanduser().resolve()
            if base_dir.exists():
                return base_dir
    except FileNotFoundError:
        pass

    paths = collection_service.get_paths(collection_id)
    if not paths.output_dir.exists():
        raise HTTPException(status_code=404, detail=f"集合输出目录不存在: {paths.output_dir}")
    return paths.output_dir.resolve()


def load_graph_payload(
    base_dir: Path,
    max_nodes: int,
    min_weight: float,
    community_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, str | None]:
    nodes_payload, edges_payload, truncated, community_label, _ = (
        load_graph_payload_from_storage(
            base_dir=base_dir,
            max_nodes=max_nodes,
            min_weight=min_weight,
            community_id=community_id,
            include_community=False,
        )
    )
    return nodes_payload, edges_payload, truncated, community_label


def to_graphml(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bytes:
    return render_graphml(nodes, edges)


__all__ = [
    "artifact_registry_service",
    "collection_service",
    "load_graph_payload",
    "resolve_collection_output_dir",
    "to_graphml",
]
