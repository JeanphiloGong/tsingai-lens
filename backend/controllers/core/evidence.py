from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from application.core.document_profile_service import (
    DocumentContentNotReadyError,
    DocumentNotFoundError,
)
from application.core.evidence_card_service import (
    EvidenceCardNotFoundError,
    EvidenceCardService,
    EvidenceCardsNotReadyError,
)
from controllers.schemas.core.evidence import (
    EvidenceCardListResponse,
    EvidenceTracebackResponse,
)

router = APIRouter(prefix="/collections", tags=["evidence"])
evidence_card_service = EvidenceCardService()


def _evidence_cards_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "evidence_cards_not_ready",
        "message": "The collection does not have evidence cards yet. Finish indexing first.",
        "collection_id": collection_id,
    }


@router.get(
    "/{collection_id}/evidence/cards",
    response_model=EvidenceCardListResponse,
    summary="列出 collection 的 evidence cards",
)
async def list_collection_evidence_cards(
    collection_id: str,
    limit: Annotated[int, Query(ge=1, le=500, description="返回数量")] = 50,
    offset: Annotated[int, Query(ge=0, description="偏移量")] = 0,
) -> EvidenceCardListResponse:
    try:
        payload = evidence_card_service.list_evidence_cards(
            collection_id,
            offset=offset,
            limit=limit,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvidenceCardsNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_evidence_cards_not_ready_detail(exc.collection_id),
        ) from exc
    return EvidenceCardListResponse(**payload)


@router.get(
    "/{collection_id}/evidence/{evidence_id}/traceback",
    response_model=EvidenceTracebackResponse,
    summary="读取单个 evidence 的原文 traceback",
)
async def get_collection_evidence_traceback(
    collection_id: str,
    evidence_id: str,
) -> EvidenceTracebackResponse:
    try:
        payload = evidence_card_service.get_evidence_traceback(collection_id, evidence_id)
    except EvidenceCardNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "evidence_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "evidence_id": exc.evidence_id,
            },
        ) from exc
    except EvidenceCardsNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_evidence_cards_not_ready_detail(exc.collection_id),
        ) from exc
    except DocumentContentNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_content_not_ready",
                "message": "The collection does not have document content yet. Finish indexing first.",
                "collection_id": exc.collection_id,
            },
        ) from exc
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
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return EvidenceTracebackResponse(**payload)
