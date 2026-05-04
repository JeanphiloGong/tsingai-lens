from __future__ import annotations

from fastapi import APIRouter, HTTPException

from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
    ResearchViewDocumentNotFoundError,
    ResearchViewNotReadyError,
)
from controllers.schemas.core.research_view import (
    CollectionAggregationResponse,
    PaperAggregationResponse,
)

router = APIRouter(prefix="/collections", tags=["research-view"])
research_view_service = ResearchViewAggregationService()


def _research_view_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "research_view_not_ready",
        "message": "The collection does not have research-view inputs yet. Finish indexing first.",
        "collection_id": collection_id,
    }


@router.get(
    "/{collection_id}/research-view",
    response_model=CollectionAggregationResponse,
    summary="读取 collection research view 聚合",
)
async def get_collection_research_view(
    collection_id: str,
) -> CollectionAggregationResponse:
    try:
        payload = research_view_service.get_collection_research_view(collection_id)
    except ResearchViewNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_view_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CollectionAggregationResponse(**payload)


@router.get(
    "/{collection_id}/documents/{document_id}/research-view",
    response_model=PaperAggregationResponse,
    summary="读取单篇文档 research view 聚合",
)
async def get_collection_document_research_view(
    collection_id: str,
    document_id: str,
) -> PaperAggregationResponse:
    try:
        payload = research_view_service.get_document_research_view(
            collection_id,
            document_id,
        )
    except ResearchViewDocumentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "research_view_document_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "document_id": exc.document_id,
            },
        ) from exc
    except ResearchViewNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_view_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PaperAggregationResponse(**payload)
