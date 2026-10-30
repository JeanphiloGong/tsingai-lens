from __future__ import annotations

import mimetypes
from typing import Annotated, Literal
from urllib.parse import quote

from application.core.document_profiles import service as document_profile_service
from application.source import document_markdown_service, source_archive_service
from controllers.dependencies.auth import get_current_user_id
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from utils.response import ApiResponse, make_api_response

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


document_router = APIRouter(prefix="/collections", tags=["documents"])


@document_router.get(
    "/{collection_id}/documents/profiles",
    response_model=ApiResponse[DocumentProfileListResponse],
    summary="List document profiles in a collection",
)
async def list_collection_document_profiles(
    collection_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
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
) -> Response:
    payload = await document_profile_service.list_document_profiles(
        collection_id,
        offset=offset,
        limit=limit,
        query=query,
        doc_type=doc_type,
        has_warnings=has_warnings,
        user_id=user_id,
    )
    return make_api_response(data=DocumentProfileListResponse(**payload))


@document_router.get(
    "/{collection_id}/documents/{document_id}/profile",
    response_model=ApiResponse[DocumentProfileItemResponse],
    summary="Read a document profile from a collection",
)
async def get_collection_document_profile(
    collection_id: str,
    document_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await document_profile_service.get_document_profile(
        collection_id, document_id, user_id=user_id
    )
    return make_api_response(data=DocumentProfileItemResponse(**payload))


@document_router.get(
    "/{collection_id}/documents/{document_id}/content",
    response_model=ApiResponse[DocumentContentResponse],
    summary="Read document viewer content from a collection",
)
async def get_collection_document_content(
    collection_id: str,
    document_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await document_profile_service.get_document_content(
        collection_id, document_id, user_id=user_id
    )
    return make_api_response(data=DocumentContentResponse(**payload))


@document_router.get(
    "/{collection_id}/documents/{document_id}/markdown",
    response_model=ApiResponse[DocumentMarkdownResponse],
    summary="Read a document Markdown projection from a collection",
)
async def get_collection_document_markdown(
    collection_id: str,
    document_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    *,
    request: Request,
) -> Response:
    payload = await document_markdown_service.get_document_markdown(
        collection_id, document_id, user_id=user_id,
        object_store=request.app.state.runtime.object_store,
    )
    return make_api_response(data=DocumentMarkdownResponse(**payload))


@document_router.get(
    "/{collection_id}/documents/{document_id}/source",
    summary="Stream the original source file for one document",
    response_class=Response,
    responses={
        200: {
            "description": "Source bytes, or a JSON business error.",
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                },
                "application/json": {"schema": ApiResponse[dict].model_json_schema()},
            },
        }
    },
)
async def get_collection_document_source(
    collection_id: str,
    document_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    *,
    request: Request,
) -> Response:
    payload = await source_archive_service.resolve_document_source_file(
        collection_id, document_id, source_filename=None, user_id=user_id,
        object_store=request.app.state.runtime.object_store,
    )

    filename = str(payload["filename"])
    media_type = (
        str(payload.get("media_type") or "").strip()
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )
    quoted_name = quote(filename, safe="")
    return Response(
        content=payload["content"],
        media_type=media_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quoted_name}"},
    )


@document_router.get(
    "/{collection_id}/documents/{document_id}/figures/{figure_id}/image",
    summary="Stream an extracted figure image for one parsed document",
    response_class=Response,
    responses={
        200: {
            "description": "Source bytes, or a JSON business error.",
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                },
                "application/json": {"schema": ApiResponse[dict].model_json_schema()},
            },
        }
    },
)
async def get_collection_document_figure_image(
    collection_id: str,
    document_id: str,
    figure_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    *,
    request: Request,
) -> Response:
    payload = await document_markdown_service.resolve_figure_image_file(
        collection_id, document_id, figure_id, user_id=user_id,
        object_store=request.app.state.runtime.object_store,
    )

    filename = str(payload["filename"])
    media_type = (
        str(payload.get("media_type") or "").strip()
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )
    quoted_name = quote(filename, safe="")
    return Response(
        content=payload["content"],
        media_type=media_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quoted_name}"},
    )
