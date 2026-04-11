from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from application.mock.lens_v1_service import lens_v1_mock_service
from controllers.schemas.evidence import EvidenceCardListResponse

router = APIRouter(prefix="/collections", tags=["evidence"])


@router.get(
    "/{collection_id}/evidence/cards",
    response_model=EvidenceCardListResponse,
    summary="列出 collection 的 evidence cards",
)
async def list_collection_evidence_cards(
    collection_id: str,
    limit: int = Query(default=50, ge=1, le=500, description="返回数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> EvidenceCardListResponse:
    if not lens_v1_mock_service.is_enabled() or not lens_v1_mock_service.is_mock_collection(collection_id):
        raise HTTPException(
            status_code=404,
            detail=f"evidence cards not found for collection: {collection_id}",
        )
    payload = lens_v1_mock_service.list_evidence_cards(
        collection_id,
        offset=offset,
        limit=limit,
    )
    return EvidenceCardListResponse(**payload)
