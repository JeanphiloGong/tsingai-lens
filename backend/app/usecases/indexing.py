"""Indexing use cases for collections."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.services import collection_store, ingest
from controllers.schemas import IndexRequest, IndexResponse
from retrieval.api.index import build_index
from retrieval.config.enums import IndexingMethod
from retrieval.utils.api import create_storage_from_config

logger = logging.getLogger(__name__)


def _format_context_excerpt(value: Any, limit: int = 200) -> str:
    """Return a short, log-friendly representation of arbitrary data."""
    try:
        text = str(value)
    except Exception:
        return f"<unserializable:{type(value).__name__}>"
    if len(text) > limit:
        return f"{text[:limit]}... (truncated, len={len(text)})"
    return text


async def start_indexing(request: IndexRequest) -> IndexResponse:
    config, collection_id = collection_store.load_collection_config(request.collection_id)
    logger.info(
        "Received indexing request collection_id=%s method=%s is_update_run=%s verbose=%s",
        collection_id,
        request.method or IndexingMethod.Standard,
        request.is_update_run,
        request.verbose,
    )
    if request.additional_context is not None:
        logger.debug(
            "Indexing additional_context=%s",
            _format_context_excerpt(request.additional_context),
        )

    try:
        logger.info(
            "Starting indexing pipeline method=%s is_update_run=%s",
            request.method or IndexingMethod.Standard,
            request.is_update_run,
        )
        outputs = await build_index(
            config=config,
            method=request.method or IndexingMethod.Standard,
            is_update_run=request.is_update_run,
            additional_context=request.additional_context,
            verbose=request.verbose,
        )
    except Exception as exc:
        logger.exception("Indexing pipeline execution failed")
        raise HTTPException(status_code=500, detail=f"流程执行失败: {exc}") from exc

    errors = [err for o in outputs for err in (o.errors or [])]
    status = "ok" if not errors else "error"
    logger.info(
        "Indexing finished status=%s workflows=%s error_count=%s",
        status,
        [o.workflow for o in outputs],
        len(errors),
    )
    if errors:
        logger.warning("Indexing completed with errors: %s", [str(e) for e in errors])

    return IndexResponse(
        status=status,
        workflows=[o.workflow for o in outputs],
        errors=[str(e) for e in errors] or None,
        output_path=str(getattr(config.output, "base_dir", "") or ""),
        stored_input_path=None,
    )


async def upload_and_index(
    file: UploadFile,
    collection_id: str | None,
    method: IndexingMethod | str,
    is_update_run: bool,
    verbose: bool,
) -> IndexResponse:
    """Upload a document to the configured input storage and run the pipeline."""
    config, resolved_collection_id = collection_store.load_collection_config(collection_id)
    logger.info(
        "Received upload for indexing collection_id=%s filename=%s method=%s is_update_run=%s verbose=%s",
        resolved_collection_id,
        file.filename if file else None,
        method,
        is_update_run,
        verbose,
    )

    try:
        input_storage = create_storage_from_config(config.input.storage)
        raw_bytes = await file.read()
        suffix = (file.filename or "").lower()
        if suffix.endswith(".pdf"):
            logger.info("PDF detected; extracting text before indexing")
            text = ingest.pdf_to_text(raw_bytes)
            stored_name = f"uploads/{uuid4()}_{file.filename}.txt"
            payload = text.encode("utf-8")
        else:
            stored_name = f"uploads/{uuid4()}_{file.filename}"
            payload = raw_bytes

        logger.info(
            "[usecase.indexing] Storing uploaded file filename=%s target_key=%s size_bytes=%s",
            file.filename,
            stored_name,
            len(payload),
        )
        await input_storage.set(stored_name, payload)
        stored_path = (
            Path(config.input.storage.base_dir) / stored_name
            if getattr(config.input.storage, "base_dir", None)
            else stored_name
        )
        logger.debug(
            "Upload stored base_dir=%s stored_path=%s",
            getattr(config.input.storage, "base_dir", None),
            stored_path,
        )
    except Exception as exc:
        logger.exception("Failed to store uploaded file into input storage")
        raise HTTPException(status_code=500, detail=f"文件保存失败: {exc}") from exc

    try:
        logger.info(
            "Starting indexing pipeline for uploaded file method=%s is_update_run=%s",
            method or IndexingMethod.Standard,
            is_update_run,
        )
        outputs = await build_index(
            config=config,
            method=method or IndexingMethod.Standard,
            is_update_run=is_update_run,
            additional_context=None,
            verbose=verbose,
        )
    except Exception as exc:
        logger.exception("Indexing pipeline execution failed")
        raise HTTPException(status_code=500, detail=f"流程执行失败: {exc}") from exc

    errors = [err for o in outputs for err in (o.errors or [])]
    status = "ok" if not errors else "error"
    logger.info(
        "Indexing finished for upload status=%s workflows=%s error_count=%s stored_input_path=%s",
        status,
        [o.workflow for o in outputs],
        len(errors),
        stored_path,
    )
    if errors:
        logger.warning("Indexing completed with errors: %s", [str(e) for e in errors])

    return IndexResponse(
        status=status,
        workflows=[o.workflow for o in outputs],
        errors=[str(e) for e in errors] or None,
        output_path=str(getattr(config.output, "base_dir", "") or ""),
        stored_input_path=str(stored_path),
    )
