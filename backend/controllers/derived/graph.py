from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

import application.derived.graph_service as graph_service
from controllers.schemas.derived.graph import (
    CollectionGraphNeighborhoodResponse,
    CollectionGraphResponse,
)

router = APIRouter(prefix="/collections", tags=["graph"])


def _collection_not_found_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "collection_not_found",
        "message": "The collection does not exist.",
        "collection_id": collection_id,
    }


def _graph_not_ready_detail(
    collection_id: str,
    output_dir: str,
    missing_artifacts: list[str],
) -> dict[str, str | list[str]]:
    return {
        "code": "graph_not_ready",
        "message": "The collection does not have graph artifacts yet. Finish indexing first.",
        "collection_id": collection_id,
        "output_path": output_dir,
        "missing_artifacts": missing_artifacts,
    }


def _graph_node_not_found_detail(
    collection_id: str,
    node_id: str,
) -> dict[str, str]:
    return {
        "code": "graph_node_not_found",
        "message": "The requested node does not exist in the Core-derived graph.",
        "collection_id": collection_id,
        "node_id": node_id,
    }


@router.get(
    "/{collection_id}/graph",
    response_model=CollectionGraphResponse,
    summary="获取集合图数据",
)
async def get_collection_graph(
    collection_id: str,
    max_nodes: int = Query(default=200, ge=1, le=2000),
    min_weight: float = Query(default=0.0, ge=0.0),
) -> CollectionGraphResponse:
    try:
        payload = graph_service.get_collection_graph(
            collection_id=collection_id,
            max_nodes=max_nodes,
            min_weight=min_weight,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_collection_not_found_detail(collection_id),
        ) from exc
    except graph_service.GraphNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_graph_not_ready_detail(
                collection_id=exc.collection_id,
                output_dir=str(exc.output_dir),
                missing_artifacts=exc.missing_artifacts,
            ),
        ) from exc
    return CollectionGraphResponse(**payload)


@router.get("/{collection_id}/graphml", summary="导出集合 GraphML")
async def export_collection_graphml(
    collection_id: str,
    max_nodes: int = Query(default=200, ge=1, le=2000),
    min_weight: float = Query(default=0.0, ge=0.0),
) -> Response:
    try:
        graphml_bytes, filename = graph_service.build_graphml(
            collection_id=collection_id,
            max_nodes=max_nodes,
            min_weight=min_weight,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_collection_not_found_detail(collection_id),
        ) from exc
    except graph_service.GraphNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_graph_not_ready_detail(
                collection_id=exc.collection_id,
                output_dir=str(exc.output_dir),
                missing_artifacts=exc.missing_artifacts,
            ),
        ) from exc
    return Response(
        content=graphml_bytes,
        media_type="application/graphml+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{collection_id}/graph/nodes/{node_id}/neighbors",
    response_model=CollectionGraphNeighborhoodResponse,
    summary="获取节点一跳邻域",
)
async def get_collection_graph_neighbors(
    collection_id: str,
    node_id: str,
) -> CollectionGraphNeighborhoodResponse:
    try:
        payload = graph_service.get_collection_graph_neighbors(
            collection_id=collection_id,
            node_id=node_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_collection_not_found_detail(collection_id),
        ) from exc
    except graph_service.GraphNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_graph_not_ready_detail(
                collection_id=exc.collection_id,
                output_dir=str(exc.output_dir),
                missing_artifacts=exc.missing_artifacts,
            ),
        ) from exc
    except graph_service.GraphNodeNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_graph_node_not_found_detail(
                collection_id=exc.collection_id,
                node_id=exc.node_id,
            ),
        ) from exc
    return CollectionGraphNeighborhoodResponse(**payload)
