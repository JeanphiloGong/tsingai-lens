from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from application.core.research_view_aggregation_service import (
    ResearchViewAggregationService,
    ResearchViewDocumentNotFoundError,
    ResearchViewMaterialNotFoundError,
    ResearchViewNotReadyError,
)
from application.source.collection_service import CollectionService
from controllers.schemas.core.research_view import (
    CollectionAggregationResponse,
    DocumentMaterialProfileResponse,
    MaterialProfileResponse,
    MaterialSummariesResponse,
    PaperAggregationResponse,
    PaperMaterialSummariesResponse,
)
from infra.persistence.factory import build_collection_repository

router = APIRouter(prefix="/collections", tags=["research-view"])
collection_service = CollectionService(repository=build_collection_repository())
research_view_service = ResearchViewAggregationService(
    collection_service=collection_service,
)


def _research_view_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "research_view_not_ready",
        "message": "The collection does not have research-view inputs yet. Finish indexing first.",
        "collection_id": collection_id,
    }


def _research_view_material_not_found_detail(
    exc: ResearchViewMaterialNotFoundError,
) -> dict[str, str | None]:
    return {
        "code": "research_view_material_not_found",
        "message": str(exc),
        "collection_id": exc.collection_id,
        "document_id": exc.document_id,
        "material_id": exc.material_id,
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
        payload = await run_in_threadpool(
            research_view_service.get_collection_research_view,
            collection_id,
        )
    except ResearchViewNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_view_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CollectionAggregationResponse(**payload)


@router.get(
    "/{collection_id}/materials",
    response_model=MaterialSummariesResponse,
    summary="读取 collection material summaries",
)
async def list_collection_materials(
    collection_id: str,
) -> MaterialSummariesResponse:
    try:
        payload = await run_in_threadpool(
            research_view_service.list_collection_materials,
            collection_id,
        )
    except ResearchViewNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_view_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MaterialSummariesResponse(**payload)


@router.get(
    "/{collection_id}/materials/{material_id}/research-view",
    response_model=MaterialProfileResponse,
    summary="读取 collection material profile research view",
)
async def get_collection_material_research_view(
    collection_id: str,
    material_id: str,
) -> MaterialProfileResponse:
    try:
        payload = await run_in_threadpool(
            research_view_service.get_collection_material_research_view,
            collection_id,
            material_id,
        )
    except ResearchViewMaterialNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_research_view_material_not_found_detail(exc),
        ) from exc
    except ResearchViewNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_view_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MaterialProfileResponse(**payload)


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
        payload = await run_in_threadpool(
            research_view_service.get_document_research_view,
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


@router.get(
    "/{collection_id}/documents/{document_id}/materials",
    response_model=PaperMaterialSummariesResponse,
    summary="读取单篇文档内 material summaries",
)
async def list_collection_document_materials(
    collection_id: str,
    document_id: str,
) -> PaperMaterialSummariesResponse:
    try:
        payload = await run_in_threadpool(
            research_view_service.list_document_materials,
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
    return PaperMaterialSummariesResponse(**payload)


@router.get(
    "/{collection_id}/documents/{document_id}/materials/{material_id}/research-view",
    response_model=DocumentMaterialProfileResponse,
    summary="读取单篇文档内 material profile research view",
)
async def get_collection_document_material_research_view(
    collection_id: str,
    document_id: str,
    material_id: str,
) -> DocumentMaterialProfileResponse:
    try:
        payload = await run_in_threadpool(
            research_view_service.get_document_material_research_view,
            collection_id,
            document_id,
            material_id,
        )
    except ResearchViewMaterialNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=_research_view_material_not_found_detail(exc),
        ) from exc
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
    return DocumentMaterialProfileResponse(**payload)
