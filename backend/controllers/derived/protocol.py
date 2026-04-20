from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application.source.collection_service import CollectionService
import application.derived.graph_service as graph_service
from application.derived.protocol import (
    search_service as protocol_search_service,
    sop_service as protocol_sop_service,
)
from application.source.artifact_registry_service import ArtifactRegistryService

router = APIRouter(prefix="/collections", tags=["protocol"])
collection_service = CollectionService()
artifact_registry_service = ArtifactRegistryService()


def _payload_list(value: Any, field_name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail=f"{field_name} 必须是数组")
    return [str(item) for item in value]


def _protocol_not_ready_detail(
    collection_id: str,
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = artifacts or {}
    return {
        "code": "protocol_artifacts_not_ready",
        "message": "集合的 protocol 产物尚未就绪，请先完成索引任务并等待 protocol steps 生成。",
        "collection_id": collection_id,
        "artifacts": {
            "documents_generated": bool(payload.get("documents_generated")),
            "documents_ready": bool(payload.get("documents_ready")),
            "blocks_generated": bool(payload.get("blocks_generated")),
            "blocks_ready": bool(payload.get("blocks_ready")),
            "table_rows_generated": bool(payload.get("table_rows_generated")),
            "table_rows_ready": bool(payload.get("table_rows_ready")),
            "procedure_blocks_generated": bool(payload.get("procedure_blocks_generated")),
            "procedure_blocks_ready": bool(payload.get("procedure_blocks_ready")),
            "protocol_steps_generated": bool(payload.get("protocol_steps_generated")),
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

    if not artifacts.get("protocol_steps_generated"):
        raise HTTPException(
            status_code=409,
            detail=_protocol_not_ready_detail(collection_id, artifacts),
        )

    return graph_service.resolve_collection_output_dir(collection_id)


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
    target_properties = (
        _payload_list(payload.get("target_properties"), "target_properties") or []
    )
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
