from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from controllers.schemas.collection import (
    CollectionCreateRequest,
    CollectionFileListResponse,
    CollectionFileResponse,
    CollectionListResponse,
    CollectionResponse,
)
from services import protocol_search_service, protocol_sop_service
from services.artifact_registry_service import ArtifactRegistryService
from services.collection_query_service import (
    load_graph_payload,
    resolve_collection_output_dir,
    to_graphml,
)
from services.collection_service import CollectionService

router = APIRouter(prefix="/collections", tags=["collections"])
collection_service = CollectionService()
artifact_registry_service = ArtifactRegistryService()


def _payload_list(value: Any, field_name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail=f"{field_name} 必须是数组")
    return [str(item) for item in value]


def _protocol_not_ready_detail(collection_id: str, artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = artifacts or {}
    return {
        "code": "protocol_artifacts_not_ready",
        "message": "集合的 protocol 产物尚未就绪，请先完成索引任务并等待 protocol steps 生成。",
        "collection_id": collection_id,
        "artifacts": {
            "documents_ready": bool(payload.get("documents_ready")),
            "sections_ready": bool(payload.get("sections_ready")),
            "procedure_blocks_ready": bool(payload.get("procedure_blocks_ready")),
            "protocol_steps_ready": bool(payload.get("protocol_steps_ready")),
        },
    }


def _ensure_collection_protocol_ready(collection_id: str) -> Path:
    try:
        collection_service.get_collection(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        artifacts = artifact_registry_service.get(collection_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=409,
            detail=_protocol_not_ready_detail(collection_id),
        ) from None

    if not artifacts.get("protocol_steps_ready"):
        raise HTTPException(
            status_code=409,
            detail=_protocol_not_ready_detail(collection_id, artifacts),
        )

    return resolve_collection_output_dir(collection_id)


@router.post("", response_model=CollectionResponse, summary="创建论文集合")
async def create_collection(payload: CollectionCreateRequest) -> CollectionResponse:
    record = collection_service.create_collection(
        name=payload.name,
        description=payload.description,
        default_method=payload.default_method,
    )
    return CollectionResponse(**record)


@router.get("", response_model=CollectionListResponse, summary="列出论文集合")
async def list_collections() -> CollectionListResponse:
    items = [CollectionResponse(**record) for record in collection_service.list_collections()]
    return CollectionListResponse(items=items)


@router.get("/{collection_id}", response_model=CollectionResponse, summary="获取集合详情")
async def get_collection(collection_id: str) -> CollectionResponse:
    try:
        record = collection_service.get_collection(collection_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CollectionResponse(**record)


@router.post(
    "/{collection_id}/files",
    response_model=CollectionFileResponse,
    summary="上传论文到集合",
)
async def upload_collection_file(
    collection_id: str,
    file: UploadFile = File(...),
) -> CollectionFileResponse:
    try:
        content = await file.read()
        record = collection_service.add_file(
            collection_id=collection_id,
            filename=file.filename or "upload.bin",
            content=content,
            media_type=file.content_type,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"文件上传失败: {exc}") from exc
    return CollectionFileResponse(**record)


@router.get(
    "/{collection_id}/files",
    response_model=CollectionFileListResponse,
    summary="列出集合文件",
)
async def list_collection_files(collection_id: str) -> CollectionFileListResponse:
    try:
        items = [
            CollectionFileResponse(**record)
            for record in collection_service.list_files(collection_id)
        ]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CollectionFileListResponse(items=items)


@router.get("/{collection_id}/graph", summary="获取集合图数据")
async def get_collection_graph(
    collection_id: str,
    max_nodes: int = Query(default=200, ge=1, le=2000),
    min_weight: float = Query(default=0.0, ge=0.0),
    community_id: str | None = Query(default=None),
) -> dict[str, Any]:
    base_dir = resolve_collection_output_dir(collection_id)
    nodes_payload, edges_payload, truncated, community_label = load_graph_payload(
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
    base_dir = resolve_collection_output_dir(collection_id)
    nodes_payload, edges_payload, _, community_label = load_graph_payload(
        base_dir,
        max_nodes,
        min_weight,
        community_id,
    )
    graphml_bytes = to_graphml(nodes_payload, edges_payload)
    filename = f"{collection_id}"
    if community_label:
        filename += f"_{community_label}"
    filename += ".graphml"
    return Response(
        content=graphml_bytes,
        media_type="application/graphml+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{collection_id}/protocol/steps", summary="列出集合 protocol steps")
async def list_collection_protocol_steps(
    collection_id: str,
    paper_id: str | None = Query(default=None, description="按论文 ID 过滤"),
    block_type: str | None = Query(default=None, description="按 block 类型过滤"),
    limit: int = Query(default=50, ge=1, le=500, description="返回数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> dict[str, Any]:
    base_dir = _ensure_collection_protocol_ready(collection_id)
    payload = protocol_sop_service.list_protocol_steps(
        base_dir=base_dir,
        paper_id=paper_id,
        block_type=block_type,
        limit=limit,
        offset=offset,
    )
    payload["collection_id"] = collection_id
    return payload


@router.get("/{collection_id}/protocol/search", summary="检索集合 protocol steps")
async def search_collection_protocol_steps(
    collection_id: str,
    q: str = Query(..., description="检索词"),
    paper_id: str | None = Query(default=None, description="按论文 ID 过滤"),
    limit: int = Query(default=10, ge=1, le=100, description="返回数量"),
) -> dict[str, Any]:
    base_dir = _ensure_collection_protocol_ready(collection_id)
    payload = protocol_search_service.search_protocol_steps(
        base_dir=base_dir,
        query=q,
        limit=limit,
        paper_id=paper_id,
    )
    payload["collection_id"] = collection_id
    return payload


@router.post("/{collection_id}/protocol/sop", summary="为集合生成 SOP 草案")
async def build_collection_protocol_sop(
    collection_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    goal = str(payload.get("goal") or "").strip()
    paper_ids = _payload_list(payload.get("paper_ids"), "paper_ids")
    target_properties = _payload_list(payload.get("target_properties"), "target_properties") or []
    max_steps = int(payload.get("max_steps", 12))
    if max_steps < 1 or max_steps > 50:
        raise HTTPException(status_code=400, detail="max_steps 必须在 1-50 之间")
    base_dir = _ensure_collection_protocol_ready(collection_id)
    response = protocol_sop_service.build_sop_draft(
        base_dir=base_dir,
        goal=goal,
        target_properties=target_properties,
        paper_ids=paper_ids,
        max_steps=max_steps,
    )
    response["collection_id"] = collection_id
    return response
