from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from application.core.objectives.analysis_service import (
    ObjectiveAnalysisDispatchError,
)
from application.core.objectives.research_objective_service import (
    ObjectiveScopeNotReadyError,
)

from controllers.schemas.core.research_objectives import (
    FindingDetailResponse,
    FindingListResponse,
    DocumentSelectionRequest,
    ObjectiveAnalysisResponse,
    ObjectiveEvidenceListResponse,
    ObjectiveEvidenceMapResponse,
    ObjectiveScopeResponse,
    PaginatedObjectiveListResponse,
)
from controllers.schemas.source.task import TaskResponse


router = APIRouter(prefix="/collections", tags=["research-objectives"])


@router.post(
    "/{collection_id}/objective-discovery",
    response_model=TaskResponse,
    summary="Queue research question formation from selected ready documents",
)
async def discover_collection_objectives(
    collection_id: str,
    payload: DocumentSelectionRequest,
    request: Request,
) -> TaskResponse:
    try:
        task = await request.app.state.research_objective_service.start_objective_discovery(
            collection_id,
            tuple(payload.document_ids),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskResponse(**task)


@router.get(
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
        objectives=page,
        offset=offset,
        limit=limit,
        total=len(ranked_objectives),
    )


@router.get(
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
        preview = await request.app.state.research_objective_service.preview_objective_scope(
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
        **preview.to_record(),
    )


@router.post(
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
    return _to_objective_analysis_response(payload)


@router.get(
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
    return _to_objective_analysis_response(payload)


@router.get(
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


@router.get(
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


@router.get(
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


@router.get(
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


def _to_objective_analysis_response(payload: dict) -> ObjectiveAnalysisResponse:
    objective = payload["objective"]
    active = payload.get("analysis")
    published = payload.get("published_analysis")
    return ObjectiveAnalysisResponse(
        collection_id=payload["collection_id"],
        objective=payload.get("objective_record") or objective.to_record(),
        active_analysis=active.to_record() if active is not None else None,
        published_analysis=(published.to_record() if published is not None else None),
        paper_contributions=[
            item.to_record() for item in payload.get("paper_contributions") or ()
        ],
        warnings=payload.get("warnings") or [],
    )


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
