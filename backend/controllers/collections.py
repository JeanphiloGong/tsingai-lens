from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from controllers.schemas.collection import (
    CollectionCreateRequest,
    CollectionFileListResponse,
    CollectionFileResponse,
    CollectionListResponse,
    CollectionResponse,
)
from services.collection_service import CollectionService

router = APIRouter(prefix="/collections", tags=["collections"])
collection_service = CollectionService()


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
