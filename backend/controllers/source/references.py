from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from application.source.reference_workflow_service import SourceReferenceWorkflowResult


class SourceReferenceEntryResponse(BaseModel):
    reference_id: str = Field(..., description="Reference entry ID")
    document_id: str = Field(..., description="Source document ID")
    raw_reference: str = Field(..., description="Raw reference text")
    reference_index: str | None = Field(
        default=None,
        description="Reference index within the paper",
    )
    title: str | None = Field(default=None, description="Parsed title")
    authors_text: str | None = Field(default=None, description="Parsed author text")
    year: int | None = Field(default=None, description="Parsed publication year")
    doi: str | None = Field(default=None, description="Parsed DOI")
    source_block_id: str | None = Field(
        default=None,
        description="Source block for the reference entry",
    )
    page: int | None = Field(default=None, description="Reference entry page")
    confidence: float = Field(default=0.0, description="Reference parsing confidence")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Extended metadata"
    )


class SourceReferenceMentionResponse(BaseModel):
    mention_id: str = Field(..., description="In-text citation mention ID")
    document_id: str = Field(..., description="Source document ID")
    reference_id: str | None = Field(
        default=None,
        description="Matched reference entry ID",
    )
    citation_marker: str = Field(..., description="In-text citation marker")
    context_text: str = Field(..., description="Text surrounding the citation")
    source_block_id: str | None = Field(
        default=None,
        description="Source block containing the citation",
    )
    page: int | None = Field(default=None, description="In-text citation page")
    confidence: float = Field(default=0.0, description="Mention parsing confidence")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Extended metadata"
    )


class SourceReferenceResolutionResponse(BaseModel):
    resolution_id: str = Field(..., description="External metadata resolution ID")
    reference_id: str = Field(..., description="Reference entry ID")
    provider: str = Field(..., description="Resolution provider")
    status: str = Field(..., description="Resolution status")
    resolved_title: str | None = Field(default=None, description="Resolved title")
    resolved_authors_text: str | None = Field(
        default=None,
        description="Resolved author text",
    )
    resolved_year: int | None = Field(default=None, description="Resolved year")
    resolved_venue: str | None = Field(default=None, description="Resolved venue")
    resolved_doi: str | None = Field(default=None, description="Resolved DOI")
    resolved_url: str | None = Field(default=None, description="Resolved URL")
    open_access_url: str | None = Field(default=None, description="Open-access URL")
    confidence: float = Field(default=0.0, description="Resolution confidence")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Extended metadata"
    )


class SourceReferenceCandidateResponse(BaseModel):
    candidate_id: str = Field(..., description="Candidate reference ID")
    reference_id: str = Field(..., description="Reference entry ID")
    status: str = Field(..., description="Candidate status")
    relevance_score: float = Field(default=0.0, description="Relevance score")
    relevance_reason: str | None = Field(
        default=None,
        description="Relevance rationale",
    )
    cited_by_document_id: str | None = Field(
        default=None,
        description="ID of the citing document",
    )
    mention_count: int = Field(default=0, description="In-text citation count")
    representative_context: str | None = Field(
        default=None,
        description="Representative citation context",
    )
    resolved_doi: str | None = Field(default=None, description="Resolved DOI")
    resolved_url: str | None = Field(default=None, description="Resolved URL")
    open_access_url: str | None = Field(default=None, description="Open-access URL")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Extended metadata"
    )


class SourceReferenceSummaryResponse(BaseModel):
    collection_id: str = Field(..., description="Collection ID")
    entry_count: int = Field(default=0, description="Reference entry count")
    mention_count: int = Field(default=0, description="In-text citation mention count")
    resolution_count: int = Field(default=0, description="External resolution count")
    candidate_count: int = Field(default=0, description="Candidate reference count")


class SourceReferenceSetResponse(SourceReferenceSummaryResponse):
    entries: list[SourceReferenceEntryResponse] = Field(
        default_factory=list,
        description="Reference entries",
    )
    mentions: list[SourceReferenceMentionResponse] = Field(
        default_factory=list,
        description="In-text citation mentions",
    )
    resolutions: list[SourceReferenceResolutionResponse] = Field(
        default_factory=list,
        description="External resolution results",
    )
    candidates: list[SourceReferenceCandidateResponse] = Field(
        default_factory=list,
        description="Candidate references",
    )


router = APIRouter(
    prefix="/collections/{collection_id}/references",
    tags=["source-references"],
)
@router.post(
    "/build",
    response_model=SourceReferenceSummaryResponse,
    summary="Build the collection reference candidate pool",
)
async def build_collection_references(
    collection_id: str,
    request: Request,
) -> SourceReferenceSummaryResponse:
    try:
        await request.app.state.collection_service.get_collection(collection_id)
        result = await request.app.state.reference_workflow_service.build_collection_references(
            collection_id
        )
    except FileNotFoundError as exc:
        raise _not_ready_or_missing(collection_id, exc) from exc
    return SourceReferenceSummaryResponse(**result.to_summary())


@router.get(
    "",
    response_model=SourceReferenceSetResponse,
    summary="Read the collection reference candidate pool",
)
async def get_collection_references(
    collection_id: str,
    request: Request,
) -> SourceReferenceSetResponse:
    try:
        await request.app.state.collection_service.get_collection(collection_id)
        result = await request.app.state.reference_workflow_service.read_collection_references(
            collection_id
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
            SourceReferenceEntryResponse.model_validate(entry, from_attributes=True)
            for entry in references.entries
        ],
        mentions=[
            SourceReferenceMentionResponse.model_validate(mention, from_attributes=True)
            for mention in references.mentions
        ],
        resolutions=[
            SourceReferenceResolutionResponse.model_validate(
                resolution, from_attributes=True
            )
            for resolution in references.resolutions
        ],
        candidates=[
            SourceReferenceCandidateResponse.model_validate(
                candidate, from_attributes=True
            )
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
