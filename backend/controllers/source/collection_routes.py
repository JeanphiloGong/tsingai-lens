from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import asdict
from tempfile import SpooledTemporaryFile
from typing import Annotated, BinaryIO, Literal
from urllib.parse import quote

from application.source import (
    collection_service,
    source_archive_service,
    source_import_service,
)
from controllers.dependencies.auth import get_current_user_id
from domain.chat.permissions import AUTO_ACTIONS
from exceptions import RequestInvalidException
from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from repositories.collection_repository import CollectionRepo
from starlette.background import BackgroundTask
from utils.response import ApiResponse, make_api_response


class CollectionCreateRequest(BaseModel):
    """Request payload to create a logical paper collection."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, description="Collection name")
    description: str | None = Field(default=None, description="Collection description")

    @field_validator("description")
    @classmethod
    def empty_description_is_none(cls, value: str | None) -> str | None:
        return value or None


class CollectionAgentPermissionRequest(BaseModel):
    """Default Research Agent authority for new sessions in one collection."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["read_only", "confirm", "auto"]
    actions: list[str] = Field(default_factory=list, max_length=len(AUTO_ACTIONS))
    all_actions: bool = False
    expires_at: str | None = Field(
        default=None,
        description=(
            "Optional automatic-grant expiry; null keeps the grant active until revoked."
        ),
    )
    expected_revision: int = Field(ge=0)


class CollectionAgentPermissionResponse(BaseModel):
    mode: Literal["read_only", "confirm", "auto"]
    actions: list[str]
    expires_at: str | None
    revision: int


class CollectionDocumentResponse(BaseModel):
    """A current source document in a collection."""

    document_id: str = Field(..., description="Document ID")
    original_filename: str = Field(..., description="Original filename")
    stored_filename: str = Field(..., description="Stored filename")
    storage_key: str = Field(..., description="Storage key")
    sha256: str = Field(..., description="Document content hash")
    media_type: str | None = Field(default=None, description="Media type")
    status: str = Field(..., description="Document status")
    size_bytes: int = Field(default=0, description="Document size in bytes")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last preparation-state update")
    parser_version: str | None = Field(default=None)
    document_analysis_version: str | None = Field(default=None)
    source_fingerprint: str | None = Field(default=None)
    profile_fingerprint: str | None = Field(default=None)
    preparation_fingerprint: str | None = Field(default=None)


class CollectionDocumentSummaryResponse(BaseModel):
    """Browser-facing document fields needed in collection listings."""

    document_id: str = Field(..., description="Document ID")
    original_filename: str = Field(..., description="Original filename")
    media_type: str | None = Field(default=None, description="Media type")
    status: str = Field(..., description="Document preparation status")
    size_bytes: int = Field(default=0, description="Document size in bytes")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last preparation-state update")


class CollectionSummaryResponse(BaseModel):
    """Compact collection row used by the collection listing."""

    collection_id: str = Field(..., description="Collection ID")
    name: str = Field(..., description="Collection name")
    description: str | None = Field(default=None, description="Collection description")
    status: str = Field(..., description="Collection status")
    paper_count: int = Field(default=0, description="Number of current documents")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    documents: list[CollectionDocumentSummaryResponse] = Field(
        default_factory=list,
        description="Compact current document rows",
    )


class CollectionResponse(BaseModel):
    """Collection metadata and its current documents."""

    collection_id: str = Field(..., description="Collection ID")
    name: str = Field(..., description="Collection name")
    description: str | None = Field(default=None, description="Collection description")
    status: str = Field(..., description="Collection status")
    paper_count: int = Field(default=0, description="Number of current documents")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    documents: list[CollectionDocumentResponse] = Field(
        default_factory=list,
        description="Current collection documents",
    )


class CollectionListResponse(BaseModel):
    """Collection listing payload."""

    items: list[CollectionSummaryResponse] = Field(
        default_factory=list,
        description="Collections",
    )


class CollectionDeleteResponse(BaseModel):
    """Collection deletion result."""

    collection_id: str = Field(..., description="Deleted collection ID")
    deleted_at: str = Field(..., description="Deletion timestamp")


class CollectionDocumentListResponse(BaseModel):
    """Collection document listing payload."""

    items: list[CollectionDocumentResponse] = Field(
        default_factory=list,
        description="Collection documents",
    )


class CollectionSourceArchiveRequest(BaseModel):
    """Selection of original collection documents to export for reproduction."""

    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 128 for value in normalized):
            raise ValueError(
                "document_ids must contain non-empty values up to 128 characters"
            )
        if len(set(normalized)) != len(normalized):
            raise ValueError("document_ids must be unique")
        return normalized


collection_router = APIRouter(prefix="/collections", tags=["collections"])
logger = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 256 * 1024 * 1024


class UploadTooLargeError(RequestInvalidException):
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
                raise UploadTooLargeError(
                    "uploaded file exceeds the 256 MiB limit",
                    data={"code": "upload_too_large"},
                )
            buffered.write(chunk)
        buffered.seek(0)
        return buffered.read()


@collection_router.post(
    "",
    response_model=ApiResponse[CollectionResponse],
    summary="create the paper collection",
)
async def create_collection(
    payload: CollectionCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    *,
    request: Request,
) -> Response:
    # create collection of paper
    record = await collection_service.create_collection(
        name=payload.name,
        description=payload.description,
        owner_user_id=user_id,
        workspace=request.app.state.runtime.collection_workspace,
    )
    return make_api_response(data=CollectionResponse(**record))


@collection_router.get(
    "",
    response_model=ApiResponse[CollectionListResponse],
    summary="List paper collections",
)
async def list_collections(
    user_id: Annotated[str, Depends(get_current_user_id)]
) -> Response:
    items = [
        CollectionSummaryResponse(
            **asdict(record),
            paper_count=len(record.documents),
        )
        for record in await CollectionRepo.list_collections(user_id)
    ]
    return make_api_response(data=CollectionListResponse(items=items))


@collection_router.get(
    "/{collection_id}",
    response_model=ApiResponse[CollectionResponse],
    summary="Get collection details",
)
async def get_collection(
    collection_id: str, user_id: Annotated[str, Depends(get_current_user_id)]
) -> Response:
    record = await collection_service.get_collection_for_user(
        collection_id,
        user_id,
    )
    return make_api_response(data=CollectionResponse(**record))


@collection_router.get(
    "/{collection_id}/agent-permissions",
    response_model=ApiResponse[CollectionAgentPermissionResponse],
    summary="Read the default Research Agent permission for a collection",
)
async def get_collection_agent_permission(
    collection_id: str, user_id: Annotated[str, Depends(get_current_user_id)]
) -> Response:
    permission = await collection_service.get_agent_default_permission_for_user(
        collection_id,
        user_id,
    )
    return make_api_response(data=CollectionAgentPermissionResponse(**permission))


@collection_router.put(
    "/{collection_id}/agent-permissions",
    response_model=ApiResponse[CollectionAgentPermissionResponse],
    summary="Set the default Research Agent permission for a collection",
)
async def set_collection_agent_permission(
    collection_id: str,
    payload: CollectionAgentPermissionRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    permission = await collection_service.set_agent_default_permission_for_user(
        collection_id,
        user_id,
        **payload.model_dump(),
    )
    return make_api_response(data=CollectionAgentPermissionResponse(**permission))


@collection_router.delete(
    "/{collection_id}",
    response_model=ApiResponse[CollectionDeleteResponse],
    summary="Delete a paper collection",
)
async def delete_collection(
    collection_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    *,
    request: Request,
) -> Response:
    result = await collection_service.delete_collection_for_user(
        collection_id,
        user_id,
        workspace=request.app.state.runtime.collection_workspace,
    )
    return make_api_response(data=CollectionDeleteResponse(**result))


@collection_router.post(
    "/{collection_id}/documents",
    response_model=ApiResponse[CollectionDocumentResponse],
    summary="Upload a paper to a collection",
)
async def upload_collection_document(
    collection_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    file: UploadFile=File(...),
    reuse_existing: bool=False,
    *,
    request: Request,
) -> Response:
    content = await _read_upload_content(file)
    record = await source_import_service.add_document(
        collection_id=collection_id,
        filename=file.filename or "upload.bin",
        content=content,
        media_type=file.content_type,
        reuse_existing=reuse_existing,
        user_id=user_id,
        object_store=request.app.state.runtime.object_store,
    )
    return make_api_response(data=CollectionDocumentResponse(**record))


@collection_router.get(
    "/{collection_id}/documents",
    response_model=ApiResponse[CollectionDocumentListResponse],
    summary="List collection documents",
)
async def list_collection_documents(
    collection_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    collection = await collection_service.get_collection_for_user(
        collection_id, user_id
    )
    items = [CollectionDocumentResponse(**record) for record in collection["documents"]]
    return make_api_response(data=CollectionDocumentListResponse(items=items))


@collection_router.post(
    "/{collection_id}/source-archives",
    summary="Download selected original collection files for reproduction",
)
async def create_collection_source_archive(
    collection_id: str,
    payload: CollectionSourceArchiveRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    *,
    request: Request,
) -> Response:
    result = await source_archive_service.build_source_archive(
        collection_id, payload.document_ids, user_id=user_id,
        object_store=request.app.state.runtime.object_store,
    )

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
