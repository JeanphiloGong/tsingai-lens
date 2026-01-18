"""Collection management use cases."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from app.services import collection_store
from controllers.schemas import (
    CollectionCreateRequest,
    CollectionDeleteResponse,
    CollectionListResponse,
    CollectionRecord,
)

logger = logging.getLogger(__name__)


def create_collection(payload: CollectionCreateRequest) -> CollectionRecord:
    if not collection_store.DEFAULT_CONFIG_PATH.is_file():
        raise HTTPException(
            status_code=500,
            detail="默认配置不存在，请在 backend/data/configs 下提供 default.yaml",
        )
    collection_store.COLLECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    collection_id = str(uuid4())
    target_dir = collection_store.collection_dir(collection_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    collection_store.create_collection_dirs(target_dir)
    collection_store.create_collection_config(
        target_dir, collection_store.DEFAULT_CONFIG_PATH
    )
    collection_store.write_collection_meta(collection_id, payload.name)
    return CollectionRecord(
        id=collection_id,
        name=payload.name,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=None,
        status="empty",
        document_count=0,
        entity_count=0,
    )


def list_collections() -> CollectionListResponse:
    collection_store.ensure_default_collection()
    items: list[CollectionRecord] = []
    for path in sorted(collection_store.COLLECTIONS_DIR.iterdir()):
        if not path.is_dir():
            continue
        meta = collection_store.read_collection_meta(path)
        metrics = collection_store.collection_metrics(path)
        items.append(
            CollectionRecord(
                id=meta.get("id", path.name),
                name=meta.get("name"),
                created_at=meta.get("created_at", ""),
                updated_at=metrics["updated_at"],
                status=metrics["status"],
                document_count=metrics["document_count"],
                entity_count=metrics["entity_count"],
            )
        )
    return CollectionListResponse(items=items)


def delete_collection(collection_id: str) -> CollectionDeleteResponse:
    if collection_id == collection_store.DEFAULT_COLLECTION_ID:
        raise HTTPException(status_code=400, detail="默认集合禁止删除")

    target_dir = collection_store.collection_dir(collection_id)
    if not target_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"集合不存在: {collection_id}")

    try:
        resolved_dir = target_dir.resolve()
        collections_root = collection_store.COLLECTIONS_DIR.resolve()
        try:
            resolved_dir.relative_to(collections_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="非法集合 ID") from exc
        if target_dir.is_symlink():
            raise HTTPException(status_code=400, detail="集合路径不可为符号链接")
        shutil.rmtree(target_dir)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to delete collection")
        raise HTTPException(status_code=500, detail=f"集合删除失败: {exc}") from exc

    return CollectionDeleteResponse(
        id=collection_id,
        deleted_at=datetime.now(timezone.utc).isoformat(),
    )
