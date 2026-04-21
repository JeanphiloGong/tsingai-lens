from __future__ import annotations

from pathlib import Path
from typing import Any

from application.core.comparison_service import ComparisonRowsNotReadyError, ComparisonService
from application.source.collection_service import CollectionService
from application.derived.graph_projection_service import (
    load_core_graph_payload,
    missing_core_graph_artifacts,
)
from application.source.artifact_registry_service import ArtifactRegistryService
from infra.derived.graph.graphml import to_graphml as render_graphml


artifact_registry_service = ArtifactRegistryService()
collection_service = CollectionService()
_NEIGHBORHOOD_MAX_NODES = 2_147_483_647
_GRAPH_SEMANTIC_ARTIFACTS = (
    "comparable_results.parquet",
    "collection_comparable_results.parquet",
)


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


class GraphNodeNotFoundError(RuntimeError):
    """Raised when one graph node is missing from the Core-derived projection."""

    def __init__(self, collection_id: str, node_id: str) -> None:
        self.collection_id = collection_id
        self.node_id = node_id
        super().__init__(f"graph node not found: {collection_id}/{node_id}")


def _missing_graph_semantic_artifacts(base_dir: Path) -> list[str]:
    return [
        filename for filename in _GRAPH_SEMANTIC_ARTIFACTS if not (base_dir / filename).is_file()
    ]


def _missing_graph_artifacts(base_dir: Path) -> list[str]:
    missing: list[str] = []
    for filename in (
        *missing_core_graph_artifacts(base_dir),
        *_missing_graph_semantic_artifacts(base_dir),
    ):
        if filename not in missing:
            missing.append(filename)
    return missing


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
            missing_artifacts=_missing_graph_artifacts(paths.output_dir.resolve()),
        )
    return paths.output_dir.resolve()


def load_graph_payload(
    collection_id: str,
    base_dir: Path,
    max_nodes: int,
    min_weight: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    missing_artifacts = missing_core_graph_artifacts(base_dir)
    if missing_artifacts:
        raise GraphNotReadyError(
            collection_id=collection_id,
            output_dir=base_dir,
            missing_artifacts=_missing_graph_artifacts(base_dir),
        )

    try:
        comparison_rows = ComparisonService(
            collection_service=collection_service,
            artifact_registry_service=artifact_registry_service,
        ).read_comparison_rows(collection_id)
    except ComparisonRowsNotReadyError as exc:
        raise GraphNotReadyError(
            collection_id=collection_id,
            output_dir=exc.output_dir,
            missing_artifacts=_missing_graph_artifacts(base_dir),
        ) from exc

    return load_core_graph_payload(
        base_dir=base_dir,
        comparison_rows=comparison_rows,
        max_nodes=max_nodes,
        min_weight=min_weight,
    )


def get_collection_graph(
    collection_id: str,
    max_nodes: int,
    min_weight: float,
) -> dict[str, Any]:
    base_dir = resolve_collection_output_dir(collection_id)
    nodes_payload, edges_payload, truncated = load_graph_payload(
        collection_id=collection_id,
        base_dir=base_dir,
        max_nodes=max_nodes,
        min_weight=min_weight,
    )
    return {
        "collection_id": collection_id,
        "nodes": nodes_payload,
        "edges": edges_payload,
        "truncated": truncated,
    }


def build_graphml(
    collection_id: str,
    max_nodes: int,
    min_weight: float,
) -> tuple[bytes, str]:
    base_dir = resolve_collection_output_dir(collection_id)
    nodes_payload, edges_payload, _ = load_graph_payload(
        collection_id=collection_id,
        base_dir=base_dir,
        max_nodes=max_nodes,
        min_weight=min_weight,
    )
    return to_graphml(nodes_payload, edges_payload), f"{collection_id}.graphml"


def get_collection_graph_neighbors(
    collection_id: str,
    node_id: str,
) -> dict[str, Any]:
    base_dir = resolve_collection_output_dir(collection_id)
    nodes_payload, edges_payload, _ = load_graph_payload(
        collection_id=collection_id,
        base_dir=base_dir,
        max_nodes=_NEIGHBORHOOD_MAX_NODES,
        min_weight=0.0,
    )

    node_ids = {str(node.get("id")) for node in nodes_payload}
    if node_id not in node_ids:
        raise GraphNodeNotFoundError(collection_id, node_id)

    neighborhood_edges = [
        edge
        for edge in edges_payload
        if str(edge.get("source")) == node_id or str(edge.get("target")) == node_id
    ]
    neighborhood_node_ids = {node_id}
    for edge in neighborhood_edges:
        source = str(edge.get("source"))
        target = str(edge.get("target"))
        neighborhood_node_ids.add(source)
        neighborhood_node_ids.add(target)
    neighborhood_nodes = [
        node for node in nodes_payload if str(node.get("id")) in neighborhood_node_ids
    ]

    return {
        "collection_id": collection_id,
        "center_node_id": node_id,
        "nodes": neighborhood_nodes,
        "edges": neighborhood_edges,
        "truncated": False,
    }


def to_graphml(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bytes:
    return render_graphml(nodes, edges)


__all__ = [
    "artifact_registry_service",
    "build_graphml",
    "collection_service",
    "get_collection_graph_neighbors",
    "get_collection_graph",
    "GraphNodeNotFoundError",
    "GraphNotReadyError",
    "load_graph_payload",
    "resolve_collection_output_dir",
    "to_graphml",
]
