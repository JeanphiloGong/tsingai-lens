from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from application.mock.lens_v1_service import lens_v1_mock_service
from controllers.schemas.documents import DocumentProfileListResponse

router = APIRouter(prefix="/collections", tags=["documents"])


@router.get(
    "/{collection_id}/documents/profiles",
    response_model=DocumentProfileListResponse,
    summary="列出 collection 的 document profiles",
)
async def list_collection_document_profiles(
    collection_id: str,
    limit: int = Query(default=50, ge=1, le=500, description="返回数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> DocumentProfileListResponse:
    if not lens_v1_mock_service.is_enabled() or not lens_v1_mock_service.is_mock_collection(collection_id):
        raise HTTPException(
            status_code=404,
            detail=f"document profiles not found for collection: {collection_id}",
        )
    payload = lens_v1_mock_service.list_document_profiles(
        collection_id,
        offset=offset,
        limit=limit,
    )
    return DocumentProfileListResponse(**payload)
