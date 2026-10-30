from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from application.core.objectives import analysis_service as objective_analysis_service
from application.core.objectives import (
    objective_analysis_service as objective_scope_service,
)
from application.core.objectives.analysis_service import list_objectives
from controllers.core.research_objective_schemas import (
    FindingDetailResponse,
    FindingListResponse,
    FindingSummaryResponse,
    ObjectiveAnalysisResponse,
    ObjectiveAnalysisStatusResponse,
    ObjectiveEvidenceListResponse,
    ObjectiveEvidenceMapResponse,
    ObjectiveScopeResponse,
    PaginatedObjectiveListResponse,
)
from controllers.dependencies.auth import get_current_user_id
from controllers.schemas.core.research_objectives import analysis_state_response
from controllers.schemas.source.pipeline_run import PipelineRunResponse
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from utils.response import ApiResponse, make_api_response


class DocumentSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[str] = Field(min_length=1)


class FindingSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_version: int = Field(ge=1)
    language: Literal["en", "zh"] = "en"


research_objective_router = APIRouter(
    prefix="/collections", tags=["research-objectives"]
)


@research_objective_router.post(
    "/{collection_id}/objective-discovery",
    response_model=ApiResponse[PipelineRunResponse],
    summary="Queue research question formation from selected ready documents",
)
async def discover_collection_objectives(
    request: Request,
    collection_id: str,
    payload: DocumentSelectionRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    run = await request.app.state.runtime.objective_discovery_service.start_objective_discovery(
        collection_id, tuple(payload.document_ids), user_id=user_id
    )
    return make_api_response(data=PipelineRunResponse(**run))


@research_objective_router.get(
    "/{collection_id}/objectives",
    response_model=ApiResponse[PaginatedObjectiveListResponse],
    summary="List collection research objectives",
)
async def list_collection_objectives(
    collection_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> Response:
    objectives = await list_objectives(collection_id, user_id=user_id)
    ranked_objectives = list(objectives)
    page = (
        ranked_objectives[offset:]
        if limit is None
        else ranked_objectives[offset : offset + limit]
    )
    return make_api_response(
        data=PaginatedObjectiveListResponse(
            collection_id=collection_id,
            objectives=[
                {
                    **asdict(item.objective),
                    "created_at": (
                        item.created_at.isoformat() if item.created_at else None
                    ),
                    "updated_at": (
                        item.updated_at.isoformat() if item.updated_at else None
                    ),
                }
                for item in page
            ],
            offset=offset,
            limit=limit,
            total=len(ranked_objectives),
        )
    )


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/scope",
    response_model=ApiResponse[ObjectiveScopeResponse],
    summary="Preview the collection paper scope for one research objective",
)
async def preview_collection_objective_scope(
    collection_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    preview = await objective_scope_service.preview_objective_scope(
        collection_id, objective_id, user_id=user_id
    )
    return make_api_response(
        data=ObjectiveScopeResponse(
            collection_id=collection_id,
            objective_id=objective_id,
            counts=preview.counts,
            recommended_document_ids=list(preview.recommended_document_ids),
            review_document_ids=list(preview.review_document_ids),
            excluded_document_ids=list(preview.excluded_document_ids),
            decisions=[asdict(item) for item in preview.decisions],
            support_is_evidence=preview.support_is_evidence,
        )
    )


@research_objective_router.post(
    "/{collection_id}/objectives/{objective_id}/analysis",
    response_model=ApiResponse[ObjectiveAnalysisResponse],
    summary="Confirm a research objective and start analysis",
    name="run_collection_objective_analysis",  # Preserve the OpenAPI operation ID.
)
async def start_collection_objective_analysis(
    request: Request,
    collection_id: str,
    objective_id: str,
    payload: DocumentSelectionRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    result = await request.app.state.runtime.objective_analysis_service.start_analysis(
        collection_id,
        objective_id,
        tuple(payload.document_ids),
        user_id=user_id,
    )
    return make_api_response(data=_analysis_response(result))


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/analysis/status",
    response_model=ApiResponse[ObjectiveAnalysisStatusResponse],
    summary="Read lightweight research objective analysis progress",
)
async def get_collection_objective_analysis_status(
    collection_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await objective_analysis_service.get_analysis_status(
        collection_id, objective_id, user_id=user_id
    )
    return make_api_response(data=ObjectiveAnalysisStatusResponse(**payload))


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/analysis",
    response_model=ApiResponse[ObjectiveAnalysisResponse],
    summary="Read research objective analysis state",
    name="get_collection_objective_analysis",  # Preserve the OpenAPI operation ID.
)
async def get_collection_objective_analysis_state(
    collection_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    result = await objective_analysis_service.get_analysis_state(
        collection_id,
        objective_id,
        user_id=user_id,
    )
    return make_api_response(data=_analysis_response(result))


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/findings",
    response_model=ApiResponse[FindingListResponse],
    summary="List published findings",
)
async def list_objective_findings(
    collection_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    analysis_version: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Response:
    payload = await objective_analysis_service.list_findings(
        collection_id,
        objective_id,
        analysis_version=analysis_version,
        offset=offset,
        limit=limit,
        user_id=user_id,
    )
    return make_api_response(data=FindingListResponse(**payload))


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}",
    response_model=ApiResponse[FindingDetailResponse],
    summary="Read one published finding",
)
async def get_objective_finding(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    analysis_version: int | None = Query(default=None, ge=1),
) -> Response:
    payload = await objective_analysis_service.get_finding(
        collection_id,
        objective_id,
        finding_id,
        analysis_version=analysis_version,
        user_id=user_id,
    )
    return make_api_response(data=FindingDetailResponse(**payload))


@research_objective_router.post(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}/summary",
    response_model=ApiResponse[FindingSummaryResponse],
    summary="Generate a cited reading summary of a published Finding",
)
async def summarize_objective_finding(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    body: FindingSummaryRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await objective_analysis_service.summarize_finding(
        collection_id,
        objective_id,
        finding_id,
        analysis_version=body.analysis_version,
        language=body.language,
        user_id=user_id,
    )
    return make_api_response(data=FindingSummaryResponse(**payload))


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/evidence",
    response_model=ApiResponse[ObjectiveEvidenceListResponse],
    summary="List published objective evidence",
)
async def list_objective_evidence(
    collection_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    analysis_version: int | None = Query(default=None, ge=1),
    finding_id: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Response:
    payload = await objective_analysis_service.list_evidence(
        collection_id,
        objective_id,
        analysis_version=analysis_version,
        finding_id=finding_id,
        offset=offset,
        limit=limit,
        user_id=user_id,
    )
    return make_api_response(data=ObjectiveEvidenceListResponse(**payload))


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/evidence-map",
    response_model=ApiResponse[ObjectiveEvidenceMapResponse],
    summary="Read the published Objective evidence map",
)
async def get_objective_evidence_map(
    collection_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await objective_analysis_service.get_evidence_map(
        collection_id, objective_id, user_id=user_id
    )
    return make_api_response(data=ObjectiveEvidenceMapResponse(**payload))


def _analysis_response(result: dict) -> ObjectiveAnalysisResponse:
    stored = result["objective"]
    return ObjectiveAnalysisResponse(
        collection_id=result["collection_id"],
        objective={
            **asdict(stored.objective),
            "created_at": stored.created_at.isoformat() if stored.created_at else None,
            "updated_at": stored.updated_at.isoformat() if stored.updated_at else None,
        },
        active_analysis=analysis_state_response(result["analysis"]),
        published_analysis=analysis_state_response(result["published_analysis"]),
        paper_contributions=list(result["paper_contributions"]),
        evidence_review=result["evidence_review"],
        warnings=result["warnings"],
    )
