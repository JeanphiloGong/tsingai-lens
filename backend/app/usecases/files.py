"""Collection file management use cases."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.services import collection_store
from controllers.schemas import (
    CollectionFileDeleteResponse,
    CollectionFileListResponse,
    CollectionFileRecord,
    InputUploadResponse,
)
from retrieval.storage.file_pipeline_storage import FilePipelineStorage
from retrieval.utils.api import create_storage_from_config

logger = logging.getLogger(__name__)

_UUID_PREFIX_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


def _is_safe_key(key: str) -> bool:
    if not key:
        return False
    candidate = Path(key)
    if candidate.is_absolute():
        return False
    return ".." not in candidate.parts


def _extract_original_filename(key: str) -> str | None:
    name = Path(key).name
    if "_" not in name:
        return name
    prefix, remainder = name.split("_", 1)
    if _UUID_PREFIX_RE.match(prefix):
        return remainder
    return name


def _build_file_meta(
    key: str,
    base_dir: str | None,
    size_bytes: int | None,
    created_at: str | None,
) -> CollectionFileRecord:
    stored_path = str(Path(base_dir) / key) if base_dir else key
    return CollectionFileRecord(
        key=key,
        original_filename=_extract_original_filename(key),
        stored_path=stored_path,
        size_bytes=size_bytes,
        created_at=created_at,
    )


def _match_all_pattern() -> re.Pattern[str]:
    return re.compile(r".+")


def _collect_file_size(storage, key: str) -> int | None:
    if isinstance(storage, FilePipelineStorage):
        try:
            file_path = Path(storage._root_dir) / key
            if file_path.is_file():
                return file_path.stat().st_size
        except Exception:
            logger.warning("Failed to stat file size for %s", key)
    return None


def _filter_key_for_storage(storage, key: str) -> bool:
    if isinstance(storage, FilePipelineStorage):
        file_path = Path(storage._root_dir) / key
        return file_path.is_file()
    return True


async def list_collection_files(collection_id: str) -> CollectionFileListResponse:
    config, resolved_collection_id = collection_store.load_collection_config(collection_id)
    input_storage = create_storage_from_config(config.input.storage)
    base_dir = getattr(config.input.storage, "base_dir", None)

    items: list[CollectionFileRecord] = []
    for key, _ in input_storage.find(_match_all_pattern()):
        if not _is_safe_key(key):
            continue
        if not _filter_key_for_storage(input_storage, key):
            continue
        created_at = None
        try:
            created_at = await input_storage.get_creation_date(key)
        except Exception:
            logger.warning("Failed to get creation date for %s", key)
        size_bytes = _collect_file_size(input_storage, key)
        items.append(_build_file_meta(key, base_dir, size_bytes, created_at))

    items.sort(key=lambda item: item.key)

    return CollectionFileListResponse(
        collection_id=resolved_collection_id,
        count=len(items),
        items=items,
    )


async def upload_collection_files(
    collection_id: str,
    files: list[UploadFile],
) -> InputUploadResponse:
    from app.usecases import inputs as inputs_uc

    return await inputs_uc.upload_inputs(collection_id, files)


async def delete_collection_file(
    collection_id: str,
    key: str,
) -> CollectionFileDeleteResponse:
    if not _is_safe_key(key):
        raise HTTPException(status_code=400, detail="非法文件 key")

    config, resolved_collection_id = collection_store.load_collection_config(collection_id)
    input_storage = create_storage_from_config(config.input.storage)

    if not await input_storage.has(key):
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        await input_storage.delete(key)
    except Exception as exc:
        logger.exception("Failed to delete input file")
        raise HTTPException(status_code=500, detail=f"删除失败: {exc}") from exc

    return CollectionFileDeleteResponse(
        collection_id=resolved_collection_id,
        key=key,
    )
