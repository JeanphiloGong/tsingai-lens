from __future__ import annotations

from pathlib import Path
from typing import Any

from application.derived.core_fact_projection import build_core_fact_projection_frames
from application.source.collection_service import CollectionService
from application.derived.graph_projection_service import (
    load_core_graph_payload,
)
from application.source.artifact_registry_service import ArtifactRegistryService
from infra.persistence.factory import build_core_fact_repository
from infra.derived.graph.graphml import to_graphml as render_graphml


artifact_registry_service = ArtifactRegistryService()
collection_service = CollectionService()
core_fact_repository = build_core_fact_repository()
_NEIGHBORHOOD_MAX_NODES = 2_147_483_647


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
            missing_artifacts=["core_fact_repository.comparison_artifacts"],
        )
    return paths.output_dir.resolve()


def _graph_error_output_dir(collection_id: str) -> Path:
    try:
        return resolve_collection_output_dir(collection_id)
    except GraphNotReadyError as exc:
        return exc.output_dir


def load_graph_payload(
    collection_id: str,
    max_nodes: int,
    min_weight: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    collection_service.get_collection(collection_id)
    facts = core_fact_repository.read_collection_facts(collection_id)
    if not facts.comparison_artifacts_ready:
        raise GraphNotReadyError(
            collection_id=collection_id,
            output_dir=_graph_error_output_dir(collection_id),
            missing_artifacts=["core_fact_repository.comparison_artifacts"],
        )
    frames = build_core_fact_projection_frames(facts)

    return load_core_graph_payload(
        profiles=frames.document_profiles,
        evidence_cards=frames.evidence_cards,
        comparison_rows=frames.comparison_rows,
        max_nodes=max_nodes,
        min_weight=min_weight,
    )


def get_collection_graph(
    collection_id: str,
    max_nodes: int,
    min_weight: float,
) -> dict[str, Any]:
    nodes_payload, edges_payload, truncated = load_graph_payload(
        collection_id=collection_id,
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
    nodes_payload, edges_payload, _ = load_graph_payload(
        collection_id=collection_id,
        max_nodes=max_nodes,
        min_weight=min_weight,
    )
    return to_graphml(nodes_payload, edges_payload), f"{collection_id}.graphml"


def get_collection_graph_neighbors(
    collection_id: str,
    node_id: str,
) -> dict[str, Any]:
    nodes_payload, edges_payload, _ = load_graph_payload(
        collection_id=collection_id,
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
    "core_fact_repository",
    "get_collection_graph_neighbors",
    "get_collection_graph",
    "GraphNodeNotFoundError",
    "GraphNotReadyError",
    "load_graph_payload",
    "resolve_collection_output_dir",
    "to_graphml",
]
