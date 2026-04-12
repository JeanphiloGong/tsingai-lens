from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from application.graph import service as graph_service
from controllers.schemas.graph import CollectionGraphResponse

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


def _community_not_found_detail(collection_id: str, community_id: str) -> dict[str, str]:
    return {
        "code": "community_not_found",
        "message": "The requested community filter could not be resolved for this collection.",
        "collection_id": collection_id,
        "community_id": community_id,
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
    community_id: str | None = Query(default=None),
) -> CollectionGraphResponse:
    try:
        payload = graph_service.get_collection_graph(
            collection_id=collection_id,
            max_nodes=max_nodes,
            min_weight=min_weight,
            community_id=community_id,
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
    except graph_service.GraphCommunityNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_community_not_found_detail(
                collection_id=exc.collection_id,
                community_id=exc.community_id,
            ),
        ) from exc
    return CollectionGraphResponse(**payload)


@router.get("/{collection_id}/graphml", summary="导出集合 GraphML")
async def export_collection_graphml(
    collection_id: str,
    max_nodes: int = Query(default=200, ge=1, le=2000),
    min_weight: float = Query(default=0.0, ge=0.0),
    community_id: str | None = Query(default=None),
) -> Response:
    try:
        graphml_bytes, filename = graph_service.build_graphml(
            collection_id=collection_id,
            max_nodes=max_nodes,
            min_weight=min_weight,
            community_id=community_id,
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
    except graph_service.GraphCommunityNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_community_not_found_detail(
                collection_id=exc.collection_id,
                community_id=exc.community_id,
            ),
        ) from exc
    return Response(
        content=graphml_bytes,
        media_type="application/graphml+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
