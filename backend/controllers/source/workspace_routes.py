from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import asdict
from tempfile import SpooledTemporaryFile
from typing import Annotated, BinaryIO
from urllib.parse import quote

from application.source import workspace_service
from document.application import archive as source_archive_service
from document.application import import_service as source_import_service
from controllers.dependencies.auth import get_current_user_id
from exceptions import RequestInvalidException
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from repositories.workspace_repository import WorkspaceRepo, StoredWorkspace, StoredDocument
from starlette.background import BackgroundTask
from utils.response import ApiResponse, make_api_response


class WorkspaceCreateRequest(BaseModel):
    """Request payload to create a logical paper workspace."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, description="Workspace name")
    description: str | None = Field(default=None, description="Workspace description")

    @field_validator("description")
    @classmethod
    def empty_description_is_none(cls, value: str | None) -> str | None:
        return value or None


class WorkspaceDocumentResponse(BaseModel):
    """A current source document in a workspace."""

    document_id: str = Field(..., description="Document ID")
    filename: str = Field(..., description="Document filename")
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


class WorkspaceDocumentSummaryResponse(BaseModel):
    """Browser-facing document fields needed in workspace listings."""

    document_id: str = Field(..., description="Document ID")
    filename: str = Field(..., description="Document filename")
    media_type: str | None = Field(default=None, description="Media type")
    status: str = Field(..., description="Document preparation status")
    size_bytes: int = Field(default=0, description="Document size in bytes")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last preparation-state update")


class WorkspaceSummaryResponse(BaseModel):
    """Compact workspace row used by the workspace listing."""

    workspace_id: str = Field(..., description="Workspace ID")
    name: str = Field(..., description="Workspace name")
    description: str | None = Field(default=None, description="Workspace description")
    status: str = Field(..., description="Workspace status")
    paper_count: int = Field(default=0, description="Number of current documents")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    documents: list[WorkspaceDocumentSummaryResponse] = Field(
        default_factory=list,
        description="Compact current document rows",
    )


class WorkspaceResponse(BaseModel):
    """Workspace metadata and its current documents."""

    workspace_id: str = Field(..., description="Workspace ID")
    name: str = Field(..., description="Workspace name")
    description: str | None = Field(default=None, description="Workspace description")
    status: str = Field(..., description="Workspace status")
    paper_count: int = Field(default=0, description="Number of current documents")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    documents: list[WorkspaceDocumentResponse] = Field(
        default_factory=list,
        description="Current workspace documents",
    )


class WorkspaceListResponse(BaseModel):
    """Workspace listing payload."""

    items: list[WorkspaceSummaryResponse] = Field(
        default_factory=list,
        description="Workspaces",
    )


class WorkspaceDeleteResponse(BaseModel):
    """Workspace deletion result."""

    workspace_id: str = Field(..., description="Deleted workspace ID")
    deleted_at: str = Field(..., description="Deletion timestamp")


class WorkspaceDocumentListResponse(BaseModel):
    """Workspace document listing payload."""

    items: list[WorkspaceDocumentResponse] = Field(
        default_factory=list,
        description="Workspace documents",
    )


class WorkspaceSourceArchiveRequest(BaseModel):
    """Selection of original workspace documents to export for reproduction."""

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


workspace_router = APIRouter(prefix="/workspaces", tags=["workspaces"])
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


def document_response(record: StoredDocument) -> WorkspaceDocumentResponse:
    return WorkspaceDocumentResponse(
        **asdict(record.document), storage_key=record.storage_key,
        status=record.status, parser_version=record.parser_version,
        document_analysis_version=record.document_analysis_version,
        source_fingerprint=record.source_fingerprint,
        profile_fingerprint=record.profile_fingerprint,
        preparation_fingerprint=record.preparation_fingerprint,
        created_at=record.created_at,
        updated_at=record.updated_at or record.created_at,
    )


def workspace_response(record: StoredWorkspace) -> WorkspaceResponse:
    return WorkspaceResponse(
        **asdict(record.workspace), created_at=record.created_at,
        updated_at=record.updated_at, paper_count=len(record.documents),
        documents=[document_response(item) for item in record.documents],
    )


@workspace_router.post(
    "",
    response_model=ApiResponse[WorkspaceResponse],
    summary="create the paper workspace",
)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    # create workspace of paper
    record = await workspace_service.create_workspace(
        name=payload.name,
        description=payload.description,
        owner_user_id=user_id,
    )
    return make_api_response(data=workspace_response(record))


@workspace_router.get(
    "",
    response_model=ApiResponse[WorkspaceListResponse],
    summary="List paper workspaces",
)
async def list_workspaces(
    user_id: Annotated[str, Depends(get_current_user_id)]
) -> Response:
    items = [
        WorkspaceSummaryResponse(
            **asdict(record),
            paper_count=len(record.documents),
        )
        for record in await WorkspaceRepo.list_workspaces(user_id)
    ]
    return make_api_response(data=WorkspaceListResponse(items=items))


@workspace_router.get(
    "/{workspace_id}",
    response_model=ApiResponse[WorkspaceResponse],
    summary="Get workspace details",
)
async def get_workspace(
    workspace_id: str, user_id: Annotated[str, Depends(get_current_user_id)]
) -> Response:
    record = await workspace_service.get_workspace_for_user(
        workspace_id,
        user_id,
    )
    return make_api_response(data=workspace_response(record))


@workspace_router.delete(
    "/{workspace_id}",
    response_model=ApiResponse[WorkspaceDeleteResponse],
    summary="Delete a paper workspace",
)
async def delete_workspace(
    workspace_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    result = await workspace_service.delete_workspace_for_user(
        workspace_id,
        user_id,
    )
    return make_api_response(data=WorkspaceDeleteResponse(**result))


@workspace_router.post(
    "/{workspace_id}/documents",
    response_model=ApiResponse[WorkspaceDocumentResponse],
    summary="Upload a paper to a workspace",
)
async def upload_workspace_document(
    workspace_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    file: UploadFile=File(...),
    reuse_existing: bool=False,
) -> Response:
    content = await _read_upload_content(file)
    record = await source_import_service.add_document(
        workspace_id=workspace_id,
        filename=file.filename or "upload.bin",
        content=content,
        media_type=file.content_type,
        reuse_existing=reuse_existing,
        user_id=user_id,
    )
    return make_api_response(data=document_response(record))


@workspace_router.get(
    "/{workspace_id}/documents",
    response_model=ApiResponse[WorkspaceDocumentListResponse],
    summary="List workspace documents",
)
async def list_workspace_documents(
    workspace_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    workspace = await workspace_service.get_workspace_for_user(
        workspace_id, user_id
    )
    items = [document_response(record) for record in workspace.documents]
    return make_api_response(data=WorkspaceDocumentListResponse(items=items))


@workspace_router.post(
    "/{workspace_id}/source-archives",
    summary="Download selected original workspace files for reproduction",
)
async def create_workspace_source_archive(
    workspace_id: str,
    payload: WorkspaceSourceArchiveRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    result = await source_archive_service.build_source_archive(
        workspace_id, payload.document_ids, user_id=user_id,
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
