from __future__ import annotations

from dataclasses import asdict
from typing import Literal


from application.core.objectives.analysis_service import (
    ObjectiveAnalysisDispatchError,
)
from application.core.objectives.finding_summary import FindingSummaryUnavailable
from application.core.objectives.objective_analysis_service import (
    ObjectiveScopeNotReadyError,
)
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
from controllers.schemas.source.pipeline_run import PipelineRunResponse
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field


class DocumentSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[str] = Field(min_length=1)


class FindingSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_version: int = Field(ge=1)
    language: Literal["en", "zh"] = "en"


research_objective_router = APIRouter(prefix="/collections", tags=["research-objectives"])


@research_objective_router.post(
    "/{collection_id}/objective-discovery",
    response_model=PipelineRunResponse,
    summary="Queue research question formation from selected ready documents",
)
async def discover_collection_objectives(
    collection_id: str,
    payload: DocumentSelectionRequest,
    request: Request,
) -> PipelineRunResponse:
    try:
        run = await request.app.state.objective_discovery_service.start_objective_discovery(
            collection_id,
            tuple(payload.document_ids),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PipelineRunResponse(**run)


@research_objective_router.get(
    "/{collection_id}/objectives",
    response_model=PaginatedObjectiveListResponse,
    summary="List collection research objectives",
)
async def list_collection_objectives(
    collection_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> PaginatedObjectiveListResponse:
    try:
        objectives = await (
            request.app.state.objective_repository.list_objective_records(
                collection_id
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ranked_objectives = list(objectives)
    page = (
        ranked_objectives[offset:]
        if limit is None
        else ranked_objectives[offset : offset + limit]
    )
    return PaginatedObjectiveListResponse(
        collection_id=collection_id,
        objectives=[
            {
                **asdict(item.objective),
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in page
        ],
        offset=offset,
        limit=limit,
        total=len(ranked_objectives),
    )


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/scope",
    response_model=ObjectiveScopeResponse,
    summary="Preview the collection paper scope for one research objective",
)
async def preview_collection_objective_scope(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveScopeResponse:
    try:
        preview = await request.app.state.experiment_analysis_service.preview_objective_scope(
            collection_id,
            objective_id,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ObjectiveScopeNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "objective_scope_not_ready",
                "message": str(exc),
                "collection_id": collection_id,
                "objective_id": objective_id,
            },
        ) from exc
    return ObjectiveScopeResponse(
        collection_id=collection_id,
        objective_id=objective_id,
        counts=preview.counts,
        recommended_document_ids=list(preview.recommended_document_ids),
        review_document_ids=list(preview.review_document_ids),
        excluded_document_ids=list(preview.excluded_document_ids),
        decisions=[asdict(item) for item in preview.decisions],
        support_is_evidence=preview.support_is_evidence,
    )


@research_objective_router.post(
    "/{collection_id}/objectives/{objective_id}/analysis",
    response_model=ObjectiveAnalysisResponse,
    summary="Confirm a research objective and start analysis",
    name="run_collection_objective_analysis",  # Preserve the OpenAPI operation ID.
)
async def start_collection_objective_analysis(
    collection_id: str,
    objective_id: str,
    payload: DocumentSelectionRequest,
    request: Request,
) -> ObjectiveAnalysisResponse:
    service = request.app.state.objective_analysis_service
    try:
        payload = await service.start_analysis(
            collection_id,
            objective_id,
            tuple(payload.document_ids),
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ObjectiveAnalysisDispatchError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "objective_analysis_dispatch_failed",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "objective_id": exc.objective_id,
                "analysis_version": exc.analysis_version,
            },
        ) from exc
    objective = payload["objective"]
    active = payload.get("analysis")
    published = payload.get("published_analysis")
    return ObjectiveAnalysisResponse(
        collection_id=payload["collection_id"],
        objective={
            **asdict(objective.objective),
            "created_at": (
                objective.created_at.isoformat() if objective.created_at else None
            ),
            "updated_at": (
                objective.updated_at.isoformat() if objective.updated_at else None
            ),
        },
        active_analysis=(
            {
                "collection_id": active.collection_id,
                "objective_id": active.objective_id,
                "analysis_version": active.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in active.document_inputs
                ],
                "pipeline_version": active.pipeline_version,
                "model_name": active.model_name,
                "prompt_versions": dict(active.prompt_versions),
                "stats": {
                    "duration_ms": active.stats.duration_ms,
                    "token_usage": (
                        asdict(active.stats.token_usage)
                        if active.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [asdict(item) for item in active.stats.model_usage],
                    "unreported_request_count": active.stats.unreported_request_count,
                    "prompt_versions": dict(active.stats.prompt_versions),
                },
                "status": active.status,
                "phase": active.phase,
                "processed_document_count": active.processed_document_count,
                "total_document_count": active.total_document_count,
                "current_document_id": active.current_document_id,
                "progress_message": active.progress_message,
                "error_code": active.error_code,
                "error_message": active.error_message,
                "created_at": (
                    active.created_at.isoformat()
                    if active.created_at is not None
                    else None
                ),
                "started_at": (
                    active.started_at.isoformat()
                    if active.started_at is not None
                    else None
                ),
                "completed_at": (
                    active.completed_at.isoformat()
                    if active.completed_at is not None
                    else None
                ),
                "origin": active.origin,
                "scientific_record_source": active.scientific_record_source,
                "source_analysis_version": active.source_analysis_version,
                "created_by_user_id": active.created_by_user_id,
                "created_by_tool_call_id": active.created_by_tool_call_id,
                "abstention_reason": active.abstention_reason,
                "abstention_note": active.abstention_note,
            }
            if active is not None
            else None
        ),
        published_analysis=(
            {
                "collection_id": published.collection_id,
                "objective_id": published.objective_id,
                "analysis_version": published.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in published.document_inputs
                ],
                "pipeline_version": published.pipeline_version,
                "model_name": published.model_name,
                "prompt_versions": dict(published.prompt_versions),
                "stats": {
                    "duration_ms": published.stats.duration_ms,
                    "token_usage": (
                        asdict(published.stats.token_usage)
                        if published.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in published.stats.model_usage
                    ],
                    "unreported_request_count": published.stats.unreported_request_count,
                    "prompt_versions": dict(published.stats.prompt_versions),
                },
                "status": published.status,
                "phase": published.phase,
                "processed_document_count": published.processed_document_count,
                "total_document_count": published.total_document_count,
                "current_document_id": published.current_document_id,
                "progress_message": published.progress_message,
                "error_code": published.error_code,
                "error_message": published.error_message,
                "created_at": (
                    published.created_at.isoformat()
                    if published.created_at is not None
                    else None
                ),
                "started_at": (
                    published.started_at.isoformat()
                    if published.started_at is not None
                    else None
                ),
                "completed_at": (
                    published.completed_at.isoformat()
                    if published.completed_at is not None
                    else None
                ),
                "origin": published.origin,
                "scientific_record_source": published.scientific_record_source,
                "source_analysis_version": published.source_analysis_version,
                "created_by_user_id": published.created_by_user_id,
                "created_by_tool_call_id": published.created_by_tool_call_id,
                "abstention_reason": published.abstention_reason,
                "abstention_note": published.abstention_note,
            }
            if published is not None
            else None
        ),
        paper_contributions=[
            (
                item
                if isinstance(item, dict)
                else {
                    "collection_id": item.collection_id,
                    "objective_id": item.objective_id,
                    "analysis_version": item.analysis_version,
                    "document_id": item.document_id,
                    "analysis_status": item.analysis_status,
                    "relevance": item.relevance,
                    "paper_role": item.paper_role,
                    "contribution_summary": item.contribution_summary,
                    "material_match": list(item.material_match),
                    "changed_variables": list(item.changed_variables),
                    "measured_property_scope": list(item.measured_property_scope),
                    "test_environment_scope": list(item.test_environment_scope),
                    "exclusion_reason": item.exclusion_reason,
                    "warnings": list(item.warnings),
                    "confidence": item.confidence,
                    "evidence_disposition": item.evidence_disposition,
                    "routed_source_count": item.routed_source_count,
                    "extracted_source_count": item.extracted_source_count,
                    "comparable_evidence_count": item.comparable_evidence_count,
                    "failed_source_count": item.failed_source_count,
                    "uninspected_source_count": item.uninspected_source_count,
                    "evidence_disposition_reason": item.evidence_disposition_reason,
                    "evidence_status_counts": {
                        status: count for status, count in item.evidence_status_counts
                    },
                    "inspected_source_refs": [
                        {
                            "source_kind": source_ref.source_kind,
                            "source_ref": source_ref.source_ref,
                            "source_digest": source_ref.source_digest,
                        }
                        for source_ref in item.inspected_source_refs
                    ],
                }
            )
            for item in payload.get("paper_contributions") or ()
        ],
        evidence_review=payload.get("evidence_review")
        or {
            "total_evidence_count": 0,
            "result_count": 0,
            "comparable_evidence_count": 0,
            "gap_count": 0,
            "omitted_gap_count": 0,
            "status_counts": {},
            "gaps": [],
        },
        warnings=payload.get("warnings") or [],
    )


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/analysis/status",
    response_model=ObjectiveAnalysisStatusResponse,
    summary="Read lightweight research objective analysis progress",
)
async def get_collection_objective_analysis_status(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisStatusResponse:
    try:
        payload = await request.app.state.objective_analysis_service.get_analysis_status(
            collection_id,
            objective_id,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    return ObjectiveAnalysisStatusResponse(**payload)


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/analysis",
    response_model=ObjectiveAnalysisResponse,
    summary="Read research objective analysis state",
    name="get_collection_objective_analysis",  # Preserve the OpenAPI operation ID.
)
async def get_collection_objective_analysis_state(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    try:
        payload = await request.app.state.objective_analysis_service.get_analysis_state(
            collection_id,
            objective_id,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    objective = payload["objective"]
    active = payload.get("analysis")
    published = payload.get("published_analysis")
    return ObjectiveAnalysisResponse(
        collection_id=payload["collection_id"],
        objective={
            **asdict(objective.objective),
            "created_at": (
                objective.created_at.isoformat() if objective.created_at else None
            ),
            "updated_at": (
                objective.updated_at.isoformat() if objective.updated_at else None
            ),
        },
        active_analysis=(
            {
                "collection_id": active.collection_id,
                "objective_id": active.objective_id,
                "analysis_version": active.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in active.document_inputs
                ],
                "pipeline_version": active.pipeline_version,
                "model_name": active.model_name,
                "prompt_versions": dict(active.prompt_versions),
                "stats": {
                    "duration_ms": active.stats.duration_ms,
                    "token_usage": (
                        asdict(active.stats.token_usage)
                        if active.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [asdict(item) for item in active.stats.model_usage],
                    "unreported_request_count": active.stats.unreported_request_count,
                    "prompt_versions": dict(active.stats.prompt_versions),
                },
                "status": active.status,
                "phase": active.phase,
                "processed_document_count": active.processed_document_count,
                "total_document_count": active.total_document_count,
                "current_document_id": active.current_document_id,
                "progress_message": active.progress_message,
                "error_code": active.error_code,
                "error_message": active.error_message,
                "created_at": (
                    active.created_at.isoformat()
                    if active.created_at is not None
                    else None
                ),
                "started_at": (
                    active.started_at.isoformat()
                    if active.started_at is not None
                    else None
                ),
                "completed_at": (
                    active.completed_at.isoformat()
                    if active.completed_at is not None
                    else None
                ),
                "origin": active.origin,
                "scientific_record_source": active.scientific_record_source,
                "source_analysis_version": active.source_analysis_version,
                "created_by_user_id": active.created_by_user_id,
                "created_by_tool_call_id": active.created_by_tool_call_id,
                "abstention_reason": active.abstention_reason,
                "abstention_note": active.abstention_note,
            }
            if active is not None
            else None
        ),
        published_analysis=(
            {
                "collection_id": published.collection_id,
                "objective_id": published.objective_id,
                "analysis_version": published.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in published.document_inputs
                ],
                "pipeline_version": published.pipeline_version,
                "model_name": published.model_name,
                "prompt_versions": dict(published.prompt_versions),
                "stats": {
                    "duration_ms": published.stats.duration_ms,
                    "token_usage": (
                        asdict(published.stats.token_usage)
                        if published.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in published.stats.model_usage
                    ],
                    "unreported_request_count": published.stats.unreported_request_count,
                    "prompt_versions": dict(published.stats.prompt_versions),
                },
                "status": published.status,
                "phase": published.phase,
                "processed_document_count": published.processed_document_count,
                "total_document_count": published.total_document_count,
                "current_document_id": published.current_document_id,
                "progress_message": published.progress_message,
                "error_code": published.error_code,
                "error_message": published.error_message,
                "created_at": (
                    published.created_at.isoformat()
                    if published.created_at is not None
                    else None
                ),
                "started_at": (
                    published.started_at.isoformat()
                    if published.started_at is not None
                    else None
                ),
                "completed_at": (
                    published.completed_at.isoformat()
                    if published.completed_at is not None
                    else None
                ),
                "origin": published.origin,
                "scientific_record_source": published.scientific_record_source,
                "source_analysis_version": published.source_analysis_version,
                "created_by_user_id": published.created_by_user_id,
                "created_by_tool_call_id": published.created_by_tool_call_id,
                "abstention_reason": published.abstention_reason,
                "abstention_note": published.abstention_note,
            }
            if published is not None
            else None
        ),
        paper_contributions=[
            (
                item
                if isinstance(item, dict)
                else {
                    "collection_id": item.collection_id,
                    "objective_id": item.objective_id,
                    "analysis_version": item.analysis_version,
                    "document_id": item.document_id,
                    "analysis_status": item.analysis_status,
                    "relevance": item.relevance,
                    "paper_role": item.paper_role,
                    "contribution_summary": item.contribution_summary,
                    "material_match": list(item.material_match),
                    "changed_variables": list(item.changed_variables),
                    "measured_property_scope": list(item.measured_property_scope),
                    "test_environment_scope": list(item.test_environment_scope),
                    "exclusion_reason": item.exclusion_reason,
                    "warnings": list(item.warnings),
                    "confidence": item.confidence,
                    "evidence_disposition": item.evidence_disposition,
                    "routed_source_count": item.routed_source_count,
                    "extracted_source_count": item.extracted_source_count,
                    "comparable_evidence_count": item.comparable_evidence_count,
                    "failed_source_count": item.failed_source_count,
                    "uninspected_source_count": item.uninspected_source_count,
                    "evidence_disposition_reason": item.evidence_disposition_reason,
                    "evidence_status_counts": {
                        status: count for status, count in item.evidence_status_counts
                    },
                    "inspected_source_refs": [
                        {
                            "source_kind": source_ref.source_kind,
                            "source_ref": source_ref.source_ref,
                            "source_digest": source_ref.source_digest,
                        }
                        for source_ref in item.inspected_source_refs
                    ],
                }
            )
            for item in payload.get("paper_contributions") or ()
        ],
        evidence_review=payload.get("evidence_review")
        or {
            "total_evidence_count": 0,
            "result_count": 0,
            "comparable_evidence_count": 0,
            "gap_count": 0,
            "omitted_gap_count": 0,
            "status_counts": {},
            "gaps": [],
        },
        warnings=payload.get("warnings") or [],
    )


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/findings",
    response_model=FindingListResponse,
    summary="List published findings",
)
async def list_objective_findings(
    collection_id: str,
    objective_id: str,
    request: Request,
    analysis_version: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> FindingListResponse:
    try:
        payload = await request.app.state.objective_analysis_service.list_findings(
            collection_id,
            objective_id,
            analysis_version=analysis_version,
            offset=offset,
            limit=limit,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FindingListResponse(**payload)


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}",
    response_model=FindingDetailResponse,
    summary="Read one published finding",
)
async def get_objective_finding(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    request: Request,
    analysis_version: int | None = Query(default=None, ge=1),
) -> FindingDetailResponse:
    try:
        payload = await request.app.state.objective_analysis_service.get_finding(
            collection_id,
            objective_id,
            finding_id,
            analysis_version=analysis_version,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FindingDetailResponse(**payload)


@research_objective_router.post(
    "/{collection_id}/objectives/{objective_id}/findings/{finding_id}/summary",
    response_model=FindingSummaryResponse,
    summary="Generate a cited reading summary of a published Finding",
)
async def summarize_objective_finding(
    collection_id: str,
    objective_id: str,
    finding_id: str,
    body: FindingSummaryRequest,
    request: Request,
) -> FindingSummaryResponse:
    try:
        payload = await request.app.state.objective_analysis_service.summarize_finding(
            collection_id,
            objective_id,
            finding_id,
            analysis_version=body.analysis_version,
            language=body.language,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Published Finding not found."
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "summary_stale_analysis",
                "message": "The published analysis has changed. Reload before generating a summary.",
            },
        ) from exc
    except FindingSummaryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": str(exc),
                "message": "The evidence summary is unavailable. Original evidence remains accessible.",
            },
        ) from exc
    return FindingSummaryResponse(**payload)


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/evidence",
    response_model=ObjectiveEvidenceListResponse,
    summary="List published objective evidence",
)
async def list_objective_evidence(
    collection_id: str,
    objective_id: str,
    request: Request,
    analysis_version: int | None = Query(default=None, ge=1),
    finding_id: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> ObjectiveEvidenceListResponse:
    try:
        payload = await request.app.state.objective_analysis_service.list_evidence(
            collection_id,
            objective_id,
            analysis_version=analysis_version,
            finding_id=finding_id,
            offset=offset,
            limit=limit,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ObjectiveEvidenceListResponse(**payload)


@research_objective_router.get(
    "/{collection_id}/objectives/{objective_id}/evidence-map",
    response_model=ObjectiveEvidenceMapResponse,
    summary="Read the published Objective evidence map",
)
async def get_objective_evidence_map(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveEvidenceMapResponse:
    try:
        payload = await request.app.state.objective_analysis_service.get_evidence_map(
            collection_id,
            objective_id,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ObjectiveEvidenceMapResponse(**payload)


def _objective_not_found(
    collection_id: str,
    objective_id: str,
    exc: Exception,
) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "research_objective_not_found",
            "message": str(exc),
            "collection_id": collection_id,
            "objective_id": objective_id,
        },
    )
