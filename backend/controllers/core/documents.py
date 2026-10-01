from __future__ import annotations

import mimetypes
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from application.core.document_profiles.service import (
    DocumentContentNotReadyError,
    DocumentNotFoundError,
    DocumentProfilesNotReadyError,
)
from application.source.document_markdown_service import (
    DocumentMarkdownNotReadyError,
    SourceDocumentNotFoundError,
    SourceFigureImageNotFoundError,
    SourceFigureImageUnavailableError,
)
from application.source.source_archive_service import (
    DocumentSourceUnavailableError,
)

DocumentType = Literal["experimental", "review", "mixed", "uncertain"]
ProfileStatus = Literal["completed", "extraction_failed"]


class DocumentProfileSummaryResponse(BaseModel):
    """Collection-level rollup derived from document profiles."""

    total_documents: int = 0
    by_doc_type: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    technical_failure_count: int = 0


class DocumentProfileItemResponse(BaseModel):
    """Single document profile item."""

    document_id: str
    title: str | None = None
    doc_type: DocumentType
    profile_status: ProfileStatus = "completed"
    profile_warnings: list[str] = Field(default_factory=list)
    confidence: float


class DocumentProfileListResponse(BaseModel):
    """Collection-scoped document profile listing."""

    collection_id: str
    total: int
    count: int
    summary: DocumentProfileSummaryResponse
    items: list[DocumentProfileItemResponse] = Field(default_factory=list)


class DocumentContentBlockResponse(BaseModel):
    """Viewer-friendly Source block for one document."""

    block_id: str
    block_type: str | None = None
    heading_path: str | None = None
    heading_level: int = 0
    order: int = 0
    text: str = ""
    text_unit_ids: list[str] = Field(default_factory=list)
    page: int | None = None


class DocumentContentResponse(BaseModel):
    """Collection-scoped document viewer payload."""

    collection_id: str
    document_id: str
    title: str | None = None
    source_filename: str | None = None
    content_text: str = ""
    blocks: list[DocumentContentBlockResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentMarkdownSourceMapResponse(BaseModel):
    """Markdown source-map entry pointing back to Source artifacts."""

    markdown_anchor: str
    artifact_type: str
    artifact_id: str
    block_id: str | None = None
    table_id: str | None = None
    figure_id: str | None = None
    block_type: str | None = None
    page: int | None = None
    heading_path: str | None = None
    text_unit_ids: list[str] = Field(default_factory=list)


class DocumentMarkdownResponse(BaseModel):
    """Markdown-first display projection for one parsed document."""

    collection_id: str
    document_id: str
    title: str | None = None
    source_filename: str | None = None
    parser: str | None = None
    markdown: str = ""
    source_map: list[DocumentMarkdownSourceMapResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


router = APIRouter(prefix="/collections", tags=["documents"])


def _document_profiles_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "document_profiles_not_ready",
        "message": "The collection does not have document profiles yet. Finish indexing first.",
        "collection_id": collection_id,
    }


def _document_content_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "document_content_not_ready",
        "message": "The collection does not have document content yet. Finish indexing first.",
        "collection_id": collection_id,
    }


def _document_markdown_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "document_markdown_not_ready",
        "message": "The collection does not have parsed Markdown content yet. Finish indexing first.",
        "collection_id": collection_id,
    }


def _document_source_unavailable_detail(
    exc: DocumentSourceUnavailableError,
) -> dict[str, str]:
    return {
        "code": exc.code,
        "message": exc.message,
        "collection_id": exc.collection_id,
        "document_id": exc.document_id,
    }


def _source_not_found_detail(
    collection_id: str,
    document_id: str,
    exc: FileNotFoundError,
) -> dict[str, str]:
    message = str(exc)
    if message.startswith("collection not found"):
        return {
            "code": "collection_not_found",
            "message": "Collection not found.",
            "collection_id": collection_id,
            "document_id": document_id,
        }
    return {
        "code": "document_not_found",
        "message": "Document not found in this collection.",
        "collection_id": collection_id,
        "document_id": document_id,
    }


def _figure_image_not_found_detail(
    exc: SourceFigureImageNotFoundError,
) -> dict[str, str]:
    return {
        "code": "figure_not_found",
        "message": "Figure image not found in this document.",
        "collection_id": exc.collection_id,
        "document_id": exc.document_id,
        "figure_id": exc.figure_id,
    }


def _figure_image_unavailable_detail(
    exc: SourceFigureImageUnavailableError,
) -> dict[str, str]:
    return {
        "code": exc.code,
        "message": exc.message,
        "collection_id": exc.collection_id,
        "document_id": exc.document_id,
        "figure_id": exc.figure_id,
    }


@router.get(
    "/{collection_id}/documents/profiles",
    response_model=DocumentProfileListResponse,
    summary="List document profiles in a collection",
)
async def list_collection_document_profiles(
    collection_id: str,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500, description="Number to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Result offset")] = 0,
    query: Annotated[
        str,
        Query(
            max_length=200,
            description="Case-insensitive profile-title search",
        ),
    ] = "",
    doc_type: Annotated[
        DocumentType | None,
        Query(description="Optional document-role classification filter"),
    ] = None,
    has_warnings: Annotated[
        bool | None,
        Query(description="Optional profile-warning presence filter"),
    ] = None,
) -> DocumentProfileListResponse:
    try:
        payload = await request.app.state.document_profile_service.list_document_profiles(
            collection_id,
            offset=offset,
            limit=limit,
            query=query,
            doc_type=doc_type,
            has_warnings=has_warnings,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DocumentProfilesNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_document_profiles_not_ready_detail(exc.collection_id),
        ) from exc
    return DocumentProfileListResponse(**payload)


@router.get(
    "/{collection_id}/documents/{document_id}/profile",
    response_model=DocumentProfileItemResponse,
    summary="Read a document profile from a collection",
)
async def get_collection_document_profile(
    collection_id: str,
    document_id: str,
    request: Request,
) -> DocumentProfileItemResponse:
    try:
        payload = await request.app.state.document_profile_service.get_document_profile(
            collection_id,
            document_id,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "document_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "document_id": exc.document_id,
            },
        ) from exc
    except DocumentProfilesNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_document_profiles_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentProfileItemResponse(**payload)


@router.get(
    "/{collection_id}/documents/{document_id}/content",
    response_model=DocumentContentResponse,
    summary="Read document viewer content from a collection",
)
async def get_collection_document_content(
    collection_id: str,
    document_id: str,
    request: Request,
) -> DocumentContentResponse:
    try:
        payload = await request.app.state.document_profile_service.get_document_content(
            collection_id,
            document_id,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "document_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "document_id": exc.document_id,
            },
        ) from exc
    except DocumentContentNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_document_content_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentContentResponse(**payload)


@router.get(
    "/{collection_id}/documents/{document_id}/markdown",
    response_model=DocumentMarkdownResponse,
    summary="Read a document Markdown projection from a collection",
)
async def get_collection_document_markdown(
    collection_id: str,
    document_id: str,
    request: Request,
) -> DocumentMarkdownResponse:
    try:
        payload = await request.app.state.document_markdown_service.get_document_markdown(
            collection_id,
            document_id,
        )
    except SourceDocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "document_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "document_id": exc.document_id,
            },
        ) from exc
    except DocumentMarkdownNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_document_markdown_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentMarkdownResponse(**payload)


@router.get(
    "/{collection_id}/documents/{document_id}/source",
    summary="Stream the original source file for one document",
)
async def get_collection_document_source(
    collection_id: str,
    document_id: str,
    request: Request,
) -> Response:
    try:
        payload = await request.app.state.source_archive_service.resolve_document_source_file(
            collection_id,
            document_id,
            source_filename=None,
        )
    except DocumentSourceUnavailableError as exc:
        raise HTTPException(
            status_code=409,
            detail=_document_source_unavailable_detail(exc),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_source_not_found_detail(collection_id, document_id, exc),
        ) from exc

    filename = str(payload["filename"])
    media_type = (
        str(payload.get("media_type") or "").strip()
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )
    encoded_filename = quote(filename)
    content_disposition = (
        f"inline; filename*=utf-8''{encoded_filename}"
        if encoded_filename != filename
        else f'inline; filename="{filename}"'
    )
    return Response(
        content=payload["content"],
        media_type=media_type,
        headers={"content-disposition": content_disposition},
    )

@router.get(
    "/{collection_id}/documents/{document_id}/figures/{figure_id}/image",
    summary="Stream an extracted figure image for one parsed document",
)
async def get_collection_document_figure_image(
    collection_id: str,
    document_id: str,
    figure_id: str,
    request: Request,
) -> Response:
    try:
        payload = await request.app.state.document_markdown_service.resolve_figure_image_file(
            collection_id,
            document_id,
            figure_id,
        )
    except SourceFigureImageNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_figure_image_not_found_detail(exc),
        ) from exc
    except SourceFigureImageUnavailableError as exc:
        raise HTTPException(
            status_code=409,
            detail=_figure_image_unavailable_detail(exc),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    filename = str(payload["filename"])
    media_type = (
        str(payload.get("media_type") or "").strip()
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )
    encoded_filename = quote(filename)
    content_disposition = (
        f"inline; filename*=utf-8''{encoded_filename}"
        if encoded_filename != filename
        else f'inline; filename="{filename}"'
    )
    return Response(
        content=payload["content"],
        media_type=media_type,
        headers={"content-disposition": content_disposition},
    )
