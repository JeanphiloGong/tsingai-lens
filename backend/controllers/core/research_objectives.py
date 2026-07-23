from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from controllers.schemas.core.research_objectives import (
    FindingDetailResponse,
    FindingListResponse,
    ObjectiveAnalysisResponse,
    ObjectiveEvidenceListResponse,
    ObjectiveListResponse,
)


router = APIRouter(prefix="/collections", tags=["research-objectives"])
logger = logging.getLogger(__name__)
_objective_analysis_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="objective-analysis",
)


@router.get(
    "/{collection_id}/objectives",
    response_model=ObjectiveListResponse,
    summary="List collection research objectives",
)
async def list_collection_objectives(
    collection_id: str,
    request: Request,
) -> ObjectiveListResponse:
    try:
        objectives = await run_in_threadpool(
            request.app.state.objective_repository.list_objectives,
            collection_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ObjectiveListResponse(
        collection_id=collection_id,
        objectives=[objective.to_record() for objective in objectives],
    )


@router.get(
    "/{collection_id}/objectives/{objective_id}",
    response_model=ObjectiveAnalysisResponse,
    summary="Read a research objective",
)
async def get_collection_objective(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    return await _get_analysis_response(collection_id, objective_id, request)


@router.post(
    "/{collection_id}/objectives/{objective_id}/confirm",
    response_model=ObjectiveAnalysisResponse,
    summary="Confirm a research objective",
)
async def confirm_collection_objective(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.confirm_objective,
            collection_id,
            objective_id,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _analysis_response(payload)


@router.post(
    "/{collection_id}/objectives/{objective_id}/analysis",
    response_model=ObjectiveAnalysisResponse,
    summary="Queue a research objective analysis",
)
def run_collection_objective_analysis(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    service = request.app.state.objective_analysis_service
    try:
        payload = service.queue_analysis(collection_id, objective_id)
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    analysis = payload.get("analysis")
    if analysis is not None and analysis.status == "queued":
        future = _objective_analysis_executor.submit(
            service.run_analysis,
            collection_id,
            objective_id,
        )
        future.add_done_callback(_log_unexpected_analysis_failure)
    return _analysis_response(payload)


@router.get(
    "/{collection_id}/objectives/{objective_id}/analysis",
    response_model=ObjectiveAnalysisResponse,
    summary="Read research objective analysis status",
)
async def get_collection_objective_analysis(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    return await _get_analysis_response(collection_id, objective_id, request)


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
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.list_findings,
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
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.get_finding,
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
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.list_evidence,
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


async def _get_analysis_response(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveAnalysisResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.objective_analysis_service.get_analysis,
            collection_id,
            objective_id,
        )
    except FileNotFoundError as exc:
        raise _objective_not_found(collection_id, objective_id, exc) from exc
    return _analysis_response(payload)


def _analysis_response(payload: dict) -> ObjectiveAnalysisResponse:
    objective = payload["objective"]
    active = payload.get("analysis")
    published = payload.get("published_analysis")
    return ObjectiveAnalysisResponse(
        collection_id=payload["collection_id"],
        objective=objective.to_record(),
        active_analysis=active.to_record() if active is not None else None,
        published_analysis=(published.to_record() if published is not None else None),
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


def _log_unexpected_analysis_failure(future: Future) -> None:
    try:
        future.result()
    except Exception:  # noqa: BLE001
        logger.exception("Objective analysis crashed after route scheduling")
