"""GraphML export use case."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.services import collection_store, graphml_export

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphMLExportResult:
    content: bytes
    filename: str
    collection_id: str
    base_dir: Path
    node_count: int
    edge_count: int
    truncated: bool
    community_label: str | None
    community_level: int | None
    include_community: bool
    min_weight: float


def export_graphml(
    collection_id: str | None,
    max_nodes: int,
    min_weight: float,
    community_id: str | None,
    include_community: bool,
) -> GraphMLExportResult:
    config, resolved_collection_id = collection_store.load_collection_config(collection_id)
    base_dir = Path(getattr(config.output, "base_dir", config.root_dir))
    if not base_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"输出目录不存在: {base_dir}")

    (
        nodes_payload,
        edges_payload,
        truncated,
        community_label,
        community_level,
    ) = graphml_export.load_graph_payload(
        base_dir,
        max_nodes,
        min_weight,
        community_id,
        include_community,
    )

    graphml_bytes = graphml_export.to_graphml(nodes_payload, edges_payload)
    filename = "graph"
    if community_label:
        filename += f"_{community_label}"
    filename += ".graphml"

    logger.info(
        "Served GraphML collection_id=%s base_dir=%s nodes=%s edges=%s truncated=%s community=%s community_level=%s include_community=%s min_weight=%s",
        resolved_collection_id,
        base_dir,
        len(nodes_payload),
        len(edges_payload),
        truncated,
        community_label,
        community_level,
        include_community,
        min_weight,
    )

    return GraphMLExportResult(
        content=graphml_bytes,
        filename=filename,
        collection_id=resolved_collection_id,
        base_dir=base_dir,
        node_count=len(nodes_payload),
        edge_count=len(edges_payload),
        truncated=truncated,
        community_label=community_label,
        community_level=community_level,
        include_community=include_community,
        min_weight=min_weight,
    )
