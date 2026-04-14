from __future__ import annotations

from pathlib import Path
from typing import Any

from application.collections.service import CollectionService
from application.graph.core_projection_service import (
    load_core_graph_payload,
    missing_core_graph_artifacts,
)
from application.workspace.artifact_registry_service import ArtifactRegistryService
from infra.graph.graphml import to_graphml as render_graphml


artifact_registry_service = ArtifactRegistryService()
collection_service = CollectionService()


class GraphNotReadyError(RuntimeError):
    """Raised when a collection exists but Core graph inputs are not ready."""

    def __init__(
        self,
        collection_id: str,
        output_dir: Path,
        missing_artifacts: list[str] | None = None,
    ) -> None:
        self.collection_id = collection_id
        self.output_dir = output_dir
        self.missing_artifacts = missing_artifacts or []
        super().__init__(f"graph not ready: {collection_id}")


class GraphFilterNotSupportedError(RuntimeError):
    """Raised when a legacy graph-only filter is requested on the Core graph."""

    def __init__(self, collection_id: str, filter_name: str) -> None:
        self.collection_id = collection_id
        self.filter_name = filter_name
        super().__init__(f"graph filter not supported: {collection_id}:{filter_name}")


def resolve_collection_output_dir(collection_id: str) -> Path:
    collection_service.get_collection(collection_id)

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
        raise GraphNotReadyError(
            collection_id=collection_id,
            output_dir=paths.output_dir.resolve(),
            missing_artifacts=missing_core_graph_artifacts(paths.output_dir.resolve()),
        )
    return paths.output_dir.resolve()


def load_graph_payload(
    collection_id: str,
    base_dir: Path,
    max_nodes: int,
    min_weight: float,
    community_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, str | None]:
    if community_id is not None:
        raise GraphFilterNotSupportedError(collection_id, "community_id")

    missing_artifacts = missing_core_graph_artifacts(base_dir)
    if missing_artifacts:
        raise GraphNotReadyError(
            collection_id=collection_id,
            output_dir=base_dir,
            missing_artifacts=missing_artifacts,
        )

    return load_core_graph_payload(
        base_dir=base_dir,
        max_nodes=max_nodes,
        min_weight=min_weight,
    )


def get_collection_graph(
    collection_id: str,
    max_nodes: int,
    min_weight: float,
    community_id: str | None,
) -> dict[str, Any]:
    base_dir = resolve_collection_output_dir(collection_id)
    nodes_payload, edges_payload, truncated, community_label = load_graph_payload(
        collection_id=collection_id,
        base_dir=base_dir,
        max_nodes=max_nodes,
        min_weight=min_weight,
        community_id=community_id,
    )
    return {
        "collection_id": collection_id,
        "output_path": str(base_dir),
        "nodes": nodes_payload,
        "edges": edges_payload,
        "truncated": truncated,
        "community": community_label,
    }


def build_graphml(
    collection_id: str,
    max_nodes: int,
    min_weight: float,
    community_id: str | None,
) -> tuple[bytes, str]:
    base_dir = resolve_collection_output_dir(collection_id)
    nodes_payload, edges_payload, _, community_label = load_graph_payload(
        collection_id=collection_id,
        base_dir=base_dir,
        max_nodes=max_nodes,
        min_weight=min_weight,
        community_id=community_id,
    )
    filename = f"{collection_id}"
    if community_label:
        filename += f"_{community_label}"
    filename += ".graphml"
    return to_graphml(nodes_payload, edges_payload), filename


def to_graphml(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bytes:
    return render_graphml(nodes, edges)


__all__ = [
    "artifact_registry_service",
    "build_graphml",
    "collection_service",
    "get_collection_graph",
    "GraphFilterNotSupportedError",
    "GraphNotReadyError",
    "load_graph_payload",
    "resolve_collection_output_dir",
    "to_graphml",
]
