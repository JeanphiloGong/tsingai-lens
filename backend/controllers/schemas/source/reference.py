from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
