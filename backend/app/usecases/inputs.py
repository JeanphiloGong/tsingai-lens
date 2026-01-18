"""Input upload use cases."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.services import collection_store, ingest
from controllers.schemas import InputUploadResponse
from retrieval.utils.api import create_storage_from_config

logger = logging.getLogger(__name__)


async def upload_inputs(
    collection_id: str | None,
    files: list[UploadFile],
) -> InputUploadResponse:
    """Upload files into input storage without running the indexing pipeline."""
    if not files:
        raise HTTPException(status_code=400, detail="文件不能为空")

    config, resolved_collection_id = collection_store.load_collection_config(collection_id)
    logger.info("Uploading input files collection_id=%s", resolved_collection_id)

    try:
        input_storage = create_storage_from_config(config.input.storage)
    except Exception as exc:
        logger.exception("Failed to create input storage")
        raise HTTPException(status_code=500, detail=f"存储初始化失败: {exc}") from exc

    base_dir = getattr(config.input.storage, "base_dir", None)
    items: list[dict[str, Any]] = []
    for file in files:
        filename = file.filename
        if not filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        raw_bytes = await file.read()
        suffix = filename.lower()
        converted_to_text = False
        if suffix.endswith(".pdf"):
            logger.info("PDF detected; extracting text before storing filename=%s", filename)
            text = ingest.pdf_to_text(raw_bytes)
            stored_name = f"uploads/{uuid4()}_{filename}.txt"
            payload = text.encode("utf-8")
            converted_to_text = True
        elif suffix.endswith(".txt"):
            stored_name = f"uploads/{uuid4()}_{filename}"
            payload = raw_bytes
        else:
            raise HTTPException(status_code=400, detail="仅支持 PDF 或 TXT 文件")

        logger.info(
            "[usecase.inputs] Storing uploaded file filename=%s target_key=%s size_bytes=%s",
            filename,
            stored_name,
            len(payload),
        )
        await input_storage.set(stored_name, payload)
        stored_path = Path(base_dir) / stored_name if base_dir else stored_name
        items.append(
            {
                "original_filename": filename,
                "stored_name": stored_name,
                "stored_path": str(stored_path),
                "converted_to_text": converted_to_text,
                "size_bytes": len(payload),
            }
        )

    logger.info("Uploaded input files count=%s", len(items))
    return InputUploadResponse(count=len(items), items=items)
