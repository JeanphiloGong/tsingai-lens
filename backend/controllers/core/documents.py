from __future__ import annotations

import mimetypes
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from application.core.document_profiles.service import (
    DocumentContentNotReadyError,
    DocumentNotFoundError,
    DocumentProfilesNotReadyError,
)
from application.source.collection_service import (
    DocumentSourceUnavailableError,
)
from application.source.document_markdown_service import (
    DocumentMarkdownNotReadyError,
    SourceFigureImageNotFoundError,
    SourceFigureImageUnavailableError,
    SourceDocumentNotFoundError,
)
from controllers.schemas.core.documents import (
    DocumentContentResponse,
    DocumentMarkdownResponse,
    DocumentProfileItemResponse,
    DocumentProfileListResponse,
)

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
) -> DocumentProfileListResponse:
    try:
        payload = await request.app.state.document_profile_service.list_document_profiles(
            collection_id,
            offset=offset,
            limit=limit,
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
    document_profile_service = request.app.state.document_profile_service
    source_filename: str | None = None
    try:
        profile = await document_profile_service.get_document_profile(
            collection_id, document_id
        )
        source_filename = profile.get("source_filename")
    except (DocumentNotFoundError, DocumentProfilesNotReadyError):
        source_filename = None

    try:
        payload = await request.app.state.collection_service.resolve_document_source_file(
            collection_id,
            document_id,
            source_filename=source_filename,
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
