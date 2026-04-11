from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import Response

from application.graph import service as graph_service

router = APIRouter(prefix="/collections", tags=["graph"])


@router.get("/{collection_id}/graph", summary="获取集合图数据")
async def get_collection_graph(
    collection_id: str,
    max_nodes: int = Query(default=200, ge=1, le=2000),
    min_weight: float = Query(default=0.0, ge=0.0),
    community_id: str | None = Query(default=None),
) -> dict[str, Any]:
    base_dir = graph_service.resolve_collection_output_dir(collection_id)
    nodes_payload, edges_payload, truncated, community_label = graph_service.load_graph_payload(
        base_dir,
        max_nodes,
        min_weight,
        community_id,
    )
    return {
        "collection_id": collection_id,
        "output_path": str(base_dir),
        "nodes": nodes_payload,
        "edges": edges_payload,
        "truncated": truncated,
        "community": community_label,
    }


@router.get("/{collection_id}/graphml", summary="导出集合 GraphML")
async def export_collection_graphml(
    collection_id: str,
    max_nodes: int = Query(default=200, ge=1, le=2000),
    min_weight: float = Query(default=0.0, ge=0.0),
    community_id: str | None = Query(default=None),
) -> Response:
    base_dir = graph_service.resolve_collection_output_dir(collection_id)
    nodes_payload, edges_payload, _, community_label = graph_service.load_graph_payload(
        base_dir,
        max_nodes,
        min_weight,
        community_id,
    )
    graphml_bytes = graph_service.to_graphml(nodes_payload, edges_payload)
    filename = f"{collection_id}"
    if community_label:
        filename += f"_{community_label}"
    filename += ".graphml"
    return Response(
        content=graphml_bytes,
        media_type="application/graphml+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
