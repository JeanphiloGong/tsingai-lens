from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from application.source.collection_service import CollectionSourceArchiveError

from controllers.dependencies.auth import current_user_id
from controllers.schemas.source.collection import (
    CollectionCreateRequest,
    CollectionDeleteResponse,
    CollectionDocumentListResponse,
    CollectionDocumentResponse,
    CollectionListResponse,
    CollectionResponse,
    CollectionSourceArchiveRequest,
)

router = APIRouter(prefix="/collections", tags=["collections"])


def _stream_file(file: BinaryIO) -> Iterator[bytes]:
    while chunk := file.read(64 * 1024):
        yield chunk


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
        CollectionResponse(**record)
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
) -> CollectionDocumentResponse:
    collection_service = request.app.state.collection_service
    try:
        await collection_service.get_collection_for_user(
            collection_id, await current_user_id(request)
        )
        content = await file.read()
        record = await collection_service.add_document(
            collection_id=collection_id,
            filename=file.filename or "upload.bin",
            content=content,
            media_type=file.content_type,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"File upload failed: {exc}") from exc
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
    try:
        await collection_service.get_collection_for_user(
            collection_id,
            await current_user_id(request),
        )
        result = await collection_service.build_source_archive(
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
