from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from application.source.collection_service import CollectionService
from application.source.reference_workflow_service import (
    SourceReferenceWorkflowResult,
    SourceReferenceWorkflowService,
)
from controllers.schemas.source.reference import (
    SourceReferenceCandidateResponse,
    SourceReferenceEntryResponse,
    SourceReferenceMentionResponse,
    SourceReferenceResolutionResponse,
    SourceReferenceSetResponse,
    SourceReferenceSummaryResponse,
)
from infra.persistence.factory import build_collection_repository


router = APIRouter(
    prefix="/collections/{collection_id}/references",
    tags=["source-references"],
)
collection_service = CollectionService(repository=build_collection_repository())
reference_workflow_service = SourceReferenceWorkflowService()


@router.post(
    "/build",
    response_model=SourceReferenceSummaryResponse,
    summary="构建集合引用文献候选池",
)
async def build_collection_references(
    collection_id: str,
) -> SourceReferenceSummaryResponse:
    try:
        collection_service.get_collection(collection_id)
        result = await run_in_threadpool(
            reference_workflow_service.build_collection_references,
            collection_id,
        )
    except FileNotFoundError as exc:
        raise _not_ready_or_missing(collection_id, exc) from exc
    return SourceReferenceSummaryResponse(**result.to_summary())


@router.get(
    "",
    response_model=SourceReferenceSetResponse,
    summary="读取集合引用文献候选池",
)
async def get_collection_references(collection_id: str) -> SourceReferenceSetResponse:
    try:
        collection_service.get_collection(collection_id)
        result = await run_in_threadpool(
            reference_workflow_service.read_collection_references,
            collection_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _reference_set_response(result)


def _reference_set_response(
    result: SourceReferenceWorkflowResult,
) -> SourceReferenceSetResponse:
    references = result.references
    return SourceReferenceSetResponse(
        collection_id=result.collection_id,
        entry_count=len(references.entries),
        mention_count=len(references.mentions),
        resolution_count=len(references.resolutions),
        candidate_count=len(references.candidates),
        entries=[
            SourceReferenceEntryResponse(**entry.to_record())
            for entry in references.entries
        ],
        mentions=[
            SourceReferenceMentionResponse(**mention.to_record())
            for mention in references.mentions
        ],
        resolutions=[
            SourceReferenceResolutionResponse(**resolution.to_record())
            for resolution in references.resolutions
        ],
        candidates=[
            SourceReferenceCandidateResponse(**candidate.to_record())
            for candidate in references.candidates
        ],
    )


def _not_ready_or_missing(collection_id: str, exc: FileNotFoundError) -> HTTPException:
    message = str(exc)
    if "source artifacts not ready" in message:
        return HTTPException(
            status_code=409,
            detail={
                "code": "source_artifacts_not_ready",
                "collection_id": collection_id,
                "message": message,
            },
        )
    return HTTPException(status_code=404, detail=message)
