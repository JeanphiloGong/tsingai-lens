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
_GRAPH_CORE_ARTIFACTS = ("entities.parquet", "relationships.parquet")


class GraphNotReadyError(RuntimeError):
    """Raised when a collection exists but graph artifacts are not ready."""

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


class GraphCommunityNotFoundError(RuntimeError):
    """Raised when a requested community filter cannot be resolved."""

    def __init__(self, collection_id: str, community_id: str) -> None:
        self.collection_id = collection_id
        self.community_id = community_id
        super().__init__(f"graph community not found: {collection_id}:{community_id}")


def _missing_graph_artifacts(base_dir: Path) -> list[str]:
    return [
        filename
        for filename in _GRAPH_CORE_ARTIFACTS
        if not (base_dir / filename).is_file()
    ]


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
            missing_artifacts=list(_GRAPH_CORE_ARTIFACTS),
        )
    return paths.output_dir.resolve()


def load_graph_payload(
    collection_id: str,
    base_dir: Path,
    max_nodes: int,
    min_weight: float,
    community_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, str | None]:
    missing_artifacts = _missing_graph_artifacts(base_dir)
    if missing_artifacts:
        raise GraphNotReadyError(
            collection_id=collection_id,
            output_dir=base_dir,
            missing_artifacts=missing_artifacts,
        )

    nodes_payload, edges_payload, truncated, community_label, _ = (
        _load_graph_payload_from_storage(
            collection_id=collection_id,
            base_dir=base_dir,
            max_nodes=max_nodes,
            min_weight=min_weight,
            community_id=community_id,
        )
    )
    return nodes_payload, edges_payload, truncated, community_label


def _load_graph_payload_from_storage(
    collection_id: str,
    base_dir: Path,
    max_nodes: int,
    min_weight: float,
    community_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, str | None, int | None]:
    try:
        return load_graph_payload_from_storage(
            base_dir=base_dir,
            max_nodes=max_nodes,
            min_weight=min_weight,
            community_id=community_id,
            include_community=False,
        )
    except HTTPException as exc:
        detail = str(exc.detail)
        if exc.status_code == 404 and detail in {
            "社区数据不存在，无法筛选",
            "未找到指定社区",
        }:
            raise GraphCommunityNotFoundError(
                collection_id=collection_id,
                community_id=str(community_id),
            ) from exc
        if exc.status_code == 404 and (
            "实体数据 不存在" in detail or "关系数据 不存在" in detail
        ):
            raise GraphNotReadyError(
                collection_id=collection_id,
                output_dir=base_dir,
                missing_artifacts=_missing_graph_artifacts(base_dir),
            ) from exc
        raise


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
    "GraphCommunityNotFoundError",
    "GraphNotReadyError",
    "load_graph_payload",
    "resolve_collection_output_dir",
    "to_graphml",
]
