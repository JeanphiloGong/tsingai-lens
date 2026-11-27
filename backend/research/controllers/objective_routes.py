from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from application.core.objectives import analysis_service as objective_analysis_service
from application.core.objectives import (
    objective_analysis_service as objective_scope_service,
)
from research.application.objectives import objective_query_service as objective_detail_service
from application.core.objectives.analysis_service import list_objectives
from application.core.objectives.objective_discovery_service import start_objective_discovery
from research.controllers.objective_schemas import (
    FindingDetailResponse,
    FindingListResponse,
    FindingSummaryResponse,
    ObjectiveAnalysisResponse,
    ObjectiveAnalysisStatusResponse,
    ObjectiveDetailResponse,
    ObjectiveEvidenceListResponse,
    ObjectiveEvidenceMapResponse,
    ObjectiveScopeResponse,
    PaginatedObjectiveListResponse,
)
from controllers.dependencies.auth import get_current_user_id
from controllers.schemas.core.research_objectives import analysis_state_response
from controllers.schemas.source.pipeline_run import PipelineRunResponse, pipeline_run_response
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
    prefix="/workspaces", tags=["research-objectives"]
)


@research_objective_router.post(
    "/{workspace_id}/objective-discovery",
    response_model=ApiResponse[PipelineRunResponse],
    summary="Queue research question formation from selected ready documents",
)
async def discover_workspace_objectives(
    request: Request,
    workspace_id: str,
    payload: DocumentSelectionRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    run = await start_objective_discovery(
        workspace_id, tuple(payload.document_ids), user_id=user_id
    )
    return make_api_response(data=PipelineRunResponse(**pipeline_run_response(run)))


@research_objective_router.get(
    "/{workspace_id}/objectives",
    response_model=ApiResponse[PaginatedObjectiveListResponse],
    summary="List workspace research objectives",
)
async def list_workspace_objectives(
    workspace_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> Response:
    objectives = await list_objectives(workspace_id, user_id=user_id)
    ranked_objectives = list(objectives)
    page = (
        ranked_objectives[offset:]
        if limit is None
        else ranked_objectives[offset : offset + limit]
    )
    return make_api_response(
        data=PaginatedObjectiveListResponse(
            workspace_id=workspace_id,
            objectives=[
                {
                    "objective_id": item.objective.objective_id,
                    "rank": item.objective.rank or 1,
                    "question": item.objective.question,
                    "material_scope": list(item.objective.material_scope),
                    "variables": list(item.objective.variables),
                    "outcomes": list(item.objective.outcomes),
                    "requested_comparator": item.objective.requested_comparator,
                    "seed_document_ids": list(item.objective.seed_document_ids),
                    "origin": item.objective.origin,
                    "confirmation_status": item.objective.confirmation_status,
                    "active_analysis_version": item.objective.active_analysis_version,
                    "published_analysis_version": item.objective.published_analysis_version,
                }
                for item in page
            ],
            offset=offset,
            limit=limit,
            total=len(ranked_objectives),
        )
    )


@research_objective_router.get(
    "/{workspace_id}/objectives/{objective_id}",
    response_model=ApiResponse[ObjectiveDetailResponse],
    summary="Read one research objective",
)
async def get_workspace_objective(
    workspace_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    record = await objective_detail_service.read_objective_detail(
        workspace_id,
        objective_id,
        user_id=user_id,
    )
    objective = record.objective
    return make_api_response(
        data=ObjectiveDetailResponse(
            **asdict(objective),
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )
    )


@research_objective_router.get(
    "/{workspace_id}/objectives/{objective_id}/scope",
    response_model=ApiResponse[ObjectiveScopeResponse],
    summary="Preview the workspace paper scope for one research objective",
)
async def preview_workspace_objective_scope(
    workspace_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    preview = await objective_scope_service.preview_objective_scope(
        workspace_id, objective_id, user_id=user_id
    )
    return make_api_response(
        data=ObjectiveScopeResponse(
            workspace_id=workspace_id,
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
    "/{workspace_id}/objectives/{objective_id}/analysis",
    response_model=ApiResponse[ObjectiveAnalysisResponse],
    summary="Confirm a research objective and start analysis",
    name="run_workspace_objective_analysis",  # Preserve the OpenAPI operation ID.
)
async def start_workspace_objective_analysis(
    request: Request,
    workspace_id: str,
    objective_id: str,
    payload: DocumentSelectionRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    result = await objective_analysis_service.start_objective_analysis(
        workspace_id,
        objective_id,
        tuple(payload.document_ids),
        user_id=user_id,
    )
    return make_api_response(data=_analysis_response(result))


@research_objective_router.get(
    "/{workspace_id}/objectives/{objective_id}/analysis/status",
    response_model=ApiResponse[ObjectiveAnalysisStatusResponse],
    summary="Read lightweight research objective analysis progress",
)
async def get_workspace_objective_analysis_status(
    workspace_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await objective_analysis_service.get_analysis_status(
        workspace_id, objective_id, user_id=user_id
    )
    return make_api_response(data=ObjectiveAnalysisStatusResponse(**payload))


@research_objective_router.get(
    "/{workspace_id}/objectives/{objective_id}/analysis",
    response_model=ApiResponse[ObjectiveAnalysisResponse],
    summary="Read research objective analysis state",
    name="get_workspace_objective_analysis",  # Preserve the OpenAPI operation ID.
)
async def get_workspace_objective_analysis_state(
    workspace_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    result = await objective_analysis_service.get_analysis_state(
        workspace_id,
        objective_id,
        user_id=user_id,
    )
    return make_api_response(data=_analysis_response(result))


@research_objective_router.get(
    "/{workspace_id}/objectives/{objective_id}/findings",
    response_model=ApiResponse[FindingListResponse],
    summary="List published findings",
)
async def list_objective_findings(
    workspace_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    analysis_version: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Response:
    payload = await objective_analysis_service.list_findings(
        workspace_id,
        objective_id,
        analysis_version=analysis_version,
        offset=offset,
        limit=limit,
        user_id=user_id,
    )
    return make_api_response(data=FindingListResponse(**payload))


@research_objective_router.get(
    "/{workspace_id}/objectives/{objective_id}/findings/{finding_id}",
    response_model=ApiResponse[FindingDetailResponse],
    summary="Read one published finding",
)
async def get_objective_finding(
    workspace_id: str,
    objective_id: str,
    finding_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    analysis_version: int | None = Query(default=None, ge=1),
) -> Response:
    payload = await objective_analysis_service.get_finding(
        workspace_id,
        objective_id,
        finding_id,
        analysis_version=analysis_version,
        user_id=user_id,
    )
    return make_api_response(data=FindingDetailResponse(**payload))


@research_objective_router.post(
    "/{workspace_id}/objectives/{objective_id}/findings/{finding_id}/summary",
    response_model=ApiResponse[FindingSummaryResponse],
    summary="Generate a cited reading summary of a published Finding",
)
async def summarize_objective_finding(
    request: Request,
    workspace_id: str,
    objective_id: str,
    finding_id: str,
    body: FindingSummaryRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await objective_analysis_service.summarize_objective_finding(
        workspace_id,
        objective_id,
        finding_id,
        analysis_version=body.analysis_version,
        language=body.language,
        user_id=user_id,
    )
    return make_api_response(data=FindingSummaryResponse(**payload))


@research_objective_router.get(
    "/{workspace_id}/objectives/{objective_id}/evidence",
    response_model=ApiResponse[ObjectiveEvidenceListResponse],
    summary="List published objective evidence",
)
async def list_objective_evidence(
    workspace_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    analysis_version: int | None = Query(default=None, ge=1),
    finding_id: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Response:
    payload = await objective_analysis_service.list_evidence(
        workspace_id,
        objective_id,
        analysis_version=analysis_version,
        finding_id=finding_id,
        offset=offset,
        limit=limit,
        user_id=user_id,
    )
    return make_api_response(data=ObjectiveEvidenceListResponse(**payload))


@research_objective_router.get(
    "/{workspace_id}/objectives/{objective_id}/evidence-map",
    response_model=ApiResponse[ObjectiveEvidenceMapResponse],
    summary="Read the published Objective evidence map",
)
async def get_objective_evidence_map(
    workspace_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    payload = await objective_analysis_service.get_evidence_map(
        workspace_id, objective_id, user_id=user_id
    )
    return make_api_response(data=ObjectiveEvidenceMapResponse(**payload))


def _analysis_response(result: dict) -> ObjectiveAnalysisResponse:
    stored = result["objective"]
    return ObjectiveAnalysisResponse(
        workspace_id=result["workspace_id"],
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
