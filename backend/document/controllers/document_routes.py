from __future__ import annotations

import mimetypes
from typing import Annotated, Literal
from urllib.parse import quote

from document.application import archive, markdown
from document.application import profile_service as document_profile_service
from controllers.dependencies.auth import get_current_user_id
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from utils.response import ApiResponse, make_api_response

DocumentType = Literal["experimental", "review", "mixed", "uncertain"]


class DocumentProfileSummaryResponse(BaseModel):
    """Workspace-level rollup derived from document profiles."""

    total_documents: int = 0
    by_doc_type: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    technical_failure_count: int = 0


class DocumentProfileItemResponse(BaseModel):
    """Single document profile item."""

    document_id: str
    doc_type: DocumentType
    description: str
    source_fingerprint: str
    profile_fingerprint: str
    profile_version: str
    generated_at: str



class DocumentProfileListResponse(BaseModel):
    """Workspace-scoped document profile listing."""

    workspace_id: str
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
    """Workspace-scoped document viewer payload."""

    workspace_id: str
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

    workspace_id: str
    document_id: str
    title: str | None = None
    source_filename: str | None = None
    parser: str | None = None
    markdown: str = ""
    source_map: list[DocumentMarkdownSourceMapResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


document_router = APIRouter(prefix="/workspaces", tags=["documents"])


@document_router.get(
    "/{workspace_id}/documents/profiles",
    response_model=ApiResponse[DocumentProfileListResponse],
    summary="List document profiles in a workspace",
)
async def list_workspace_document_profiles(
    workspace_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    limit: Annotated[int, Query(ge=1, le=500, description="Number to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Result offset")] = 0,
    query: Annotated[
        str,
        Query(
            max_length=200,
            description="Case-insensitive description search",
        ),
    ] = "",
    doc_type: Annotated[
        DocumentType | None,
        Query(description="Optional document-role classification filter"),
    ] = None,

) -> Response:
    payload = await document_profile_service.list_document_profiles(
        workspace_id,
        offset=offset,
        limit=limit,
        query=query,
        doc_type=doc_type,
        user_id=user_id,
    )
    return make_api_response(data=DocumentProfileListResponse(**payload))


@document_router.get(
    "/{workspace_id}/documents/{document_id}/profile",
    response_model=ApiResponse[DocumentProfileItemResponse],
    summary="Read a document profile from a workspace",
)
async def get_workspace_document_profile(
    workspace_id: str,
    document_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await document_profile_service.get_document_profile(
        workspace_id, document_id, user_id=user_id
    )
    return make_api_response(data=DocumentProfileItemResponse(**payload))


@document_router.get(
    "/{workspace_id}/documents/{document_id}/content",
    response_model=ApiResponse[DocumentContentResponse],
    summary="Read document viewer content from a workspace",
)
async def get_workspace_document_content(
    workspace_id: str,
    document_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await document_profile_service.get_document_content(
        workspace_id, document_id, user_id=user_id
    )
    return make_api_response(data=DocumentContentResponse(**payload))


@document_router.get(
    "/{workspace_id}/documents/{document_id}/markdown",
    response_model=ApiResponse[DocumentMarkdownResponse],
    summary="Read a document Markdown projection from a workspace",
)
async def get_workspace_document_markdown(
    workspace_id: str,
    document_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await markdown.get_document_markdown(
        workspace_id, document_id, user_id=user_id,
    )
    return make_api_response(data=DocumentMarkdownResponse(**payload))


@document_router.get(
    "/{workspace_id}/documents/{document_id}/source",
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
async def get_workspace_document_source(
    workspace_id: str,
    document_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await archive.resolve_document_source_file(
        workspace_id, document_id, source_filename=None, user_id=user_id,
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
    "/{workspace_id}/documents/{document_id}/figures/{figure_id}/image",
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
async def get_workspace_document_figure_image(
    workspace_id: str,
    document_id: str,
    figure_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await markdown.resolve_figure_image_file(
        workspace_id, document_id, figure_id, user_id=user_id,
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
