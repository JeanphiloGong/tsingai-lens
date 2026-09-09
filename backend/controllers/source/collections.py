from __future__ import annotations

from dataclasses import asdict

from collections.abc import Iterator
import logging
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from application.source.source_archive_service import CollectionSourceArchiveError

from controllers.dependencies.auth import current_user_id
from controllers.schemas.source.collection import (
    CollectionCreateRequest,
    CollectionDeleteResponse,
    CollectionDocumentListResponse,
    CollectionDocumentResponse,
    CollectionListResponse,
    CollectionResponse,
    CollectionSummaryResponse,
    CollectionSourceArchiveRequest,
)

router = APIRouter(prefix="/collections", tags=["collections"])
logger = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 256 * 1024 * 1024


class UploadTooLargeError(ValueError):
    """Raised when an upload exceeds the ingestion resource limit."""


def _stream_file(file: BinaryIO) -> Iterator[bytes]:
    while chunk := file.read(64 * 1024):
        yield chunk


async def _read_upload_content(file: UploadFile) -> bytes:
    """Read an upload in bounded chunks before handing it to ingestion."""
    with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as buffered:
        total = 0
        while chunk := await file.read(64 * 1024):
            total += len(chunk)
            if total > _MAX_UPLOAD_BYTES:
                raise UploadTooLargeError("uploaded file exceeds the 256 MiB limit")
            buffered.write(chunk)
        buffered.seek(0)
        return buffered.read()


def _source_archive_error_detail(
    exc: CollectionSourceArchiveError,
) -> dict[str, str]:
    detail = {
        "code": exc.code,
        "message": exc.message,
        "collection_id": exc.collection_id,
    }
    if exc.document_id is not None:
        detail["document_id"] = exc.document_id
    return detail


@router.post("", response_model=CollectionResponse, summary="create the paper collection")
async def create_collection(
    payload: CollectionCreateRequest,
    request: Request,
) -> CollectionResponse:
    # create collection of paper
    record = await request.app.state.collection_service.create_collection(
        name=payload.name,
        description=payload.description,
        owner_user_id=await current_user_id(request),
    )
    return CollectionResponse(**record)


@router.get("", response_model=CollectionListResponse, summary="List paper collections")
async def list_collections(request: Request) -> CollectionListResponse:
    items = [
        CollectionSummaryResponse(
            **asdict(record),
            paper_count=len(record.documents),
        )
        for record in await request.app.state.collection_service.list_collections(
            await current_user_id(request)
        )
    ]
    return CollectionListResponse(items=items)


@router.get("/{collection_id}", response_model=CollectionResponse, summary="Get collection details")
async def get_collection(collection_id: str, request: Request) -> CollectionResponse:
    try:
        record = await request.app.state.collection_service.get_collection_for_user(
            collection_id,
            await current_user_id(request),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CollectionResponse(**record)


@router.delete(
    "/{collection_id}",
    response_model=CollectionDeleteResponse,
    summary="Delete a paper collection",
)
async def delete_collection(collection_id: str, request: Request) -> CollectionDeleteResponse:
    try:
        result = await request.app.state.collection_service.delete_collection_for_user(
            collection_id,
            await current_user_id(request),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CollectionDeleteResponse(**result)


@router.post(
    "/{collection_id}/documents",
    response_model=CollectionDocumentResponse,
    summary="Upload a paper to a collection",
)
async def upload_collection_document(
    collection_id: str,
    request: Request,
    file: UploadFile = File(...),
    reuse_existing: bool = False,
) -> CollectionDocumentResponse:
    collection_service = request.app.state.collection_service
    try:
        await collection_service.get_collection_for_user(
            collection_id, await current_user_id(request)
        )
        content = await _read_upload_content(file)
        record = await request.app.state.source_import_service.add_document(
            collection_id=collection_id,
            filename=file.filename or "upload.bin",
            content=content,
            media_type=file.content_type,
            reuse_existing=reuse_existing,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("File upload failed")
        raise HTTPException(status_code=500, detail="File upload failed.") from exc
    return CollectionDocumentResponse(**record)


@router.get(
    "/{collection_id}/documents",
    response_model=CollectionDocumentListResponse,
    summary="List collection documents",
)
async def list_collection_documents(
    collection_id: str,
    request: Request,
) -> CollectionDocumentListResponse:
    collection_service = request.app.state.collection_service
    try:
        await collection_service.get_collection_for_user(
            collection_id, await current_user_id(request)
        )
        collection = await collection_service.get_collection(collection_id)
        items = [
            CollectionDocumentResponse(**record)
            for record in collection["documents"]
        ]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CollectionDocumentListResponse(items=items)


@router.post(
    "/{collection_id}/source-archives",
    summary="Download selected original collection files for reproduction",
)
async def create_collection_source_archive(
    collection_id: str,
    payload: CollectionSourceArchiveRequest,
    request: Request,
) -> StreamingResponse:
    collection_service = request.app.state.collection_service
    source_archive_service = request.app.state.source_archive_service
    try:
        await collection_service.get_collection_for_user(
            collection_id,
            await current_user_id(request),
        )
        result = await source_archive_service.build_source_archive(
            collection_id,
            payload.document_ids,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CollectionSourceArchiveError as exc:
        status_code = {
            "collection_source_document_not_found": 404,
            "collection_source_archive_too_large": 413,
        }.get(exc.code, 409)
        raise HTTPException(
            status_code=status_code,
            detail=_source_archive_error_detail(exc),
        ) from exc

    archive_file = result["file"]
    filename = str(result["filename"])
    return StreamingResponse(
        _stream_file(archive_file),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; '
                f"filename*=UTF-8''{quote(filename, safe='')}"
            )
        },
        background=BackgroundTask(archive_file.close),
    )
