from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from application.core.comparison_service import (
    ComparisonRowsNotReadyError,
    ComparisonService,
)
from application.core.semantic_build.document_profile_service import (
    DocumentContentNotReadyError,
    DocumentNotFoundError,
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from controllers.schemas.core.documents import (
    DocumentComparisonSemanticListResponse,
    DocumentContentResponse,
    DocumentProfileItemResponse,
    DocumentProfileListResponse,
)

router = APIRouter(prefix="/collections", tags=["documents"])
document_profile_service = DocumentProfileService()
comparison_service = ComparisonService()


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


def _document_comparison_semantics_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "document_comparison_semantics_not_ready",
        "message": "The collection does not have document comparison semantics yet. Finish indexing first.",
        "collection_id": collection_id,
    }


@router.get(
    "/{collection_id}/documents/profiles",
    response_model=DocumentProfileListResponse,
    summary="列出 collection 的 document profiles",
)
async def list_collection_document_profiles(
    collection_id: str,
    limit: Annotated[int, Query(ge=1, le=500, description="返回数量")] = 50,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
) -> DocumentProfileListResponse:
    try:
        payload = document_profile_service.list_document_profiles(
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
    summary="读取 collection 内单个文档的 profile",
)
async def get_collection_document_profile(
    collection_id: str,
    document_id: str,
) -> DocumentProfileItemResponse:
    try:
        payload = document_profile_service.get_document_profile(collection_id, document_id)
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
    summary="读取 collection 内单个文档的查看器内容",
)
async def get_collection_document_content(
    collection_id: str,
    document_id: str,
) -> DocumentContentResponse:
    try:
        payload = document_profile_service.get_document_content(collection_id, document_id)
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
    "/{collection_id}/documents/{document_id}/comparison-semantics",
    response_model=DocumentComparisonSemanticListResponse,
    summary="读取 collection 内单个文档的 comparison semantic drilldown",
)
async def get_collection_document_comparison_semantics(
    collection_id: str,
    document_id: str,
    include_row_projections: Annotated[
        bool,
        Query(description="是否附带按需生成的 row projection"),
    ] = False,
) -> DocumentComparisonSemanticListResponse:
    try:
        payload = comparison_service.inspect_document_comparison_semantics(
            collection_id,
            document_id,
            include_row_projections=include_row_projections,
        )
        if payload["count"] == 0:
            document_profile_service.get_document_profile(collection_id, document_id)
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
    except ComparisonRowsNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_document_comparison_semantics_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload["document_id"] = document_id
    payload.pop("source_document_id", None)
    return DocumentComparisonSemanticListResponse(**payload)
