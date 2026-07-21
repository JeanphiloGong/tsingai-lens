from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import logging

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveNotFoundError,
    ResearchObjectivesNotReadyError,
)
from controllers.schemas.core.research_objectives import (
    ObjectiveAnalysisResponse,
    ObjectiveListResponse,
    ObjectiveResearchViewResponse,
)
from domain.core import ResearchObjective, ResearchUnderstanding

router = APIRouter(prefix="/collections", tags=["research-objectives"])
logger = logging.getLogger(__name__)
_objective_analysis_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="objective-analysis",
)


def _research_objectives_not_ready_detail(collection_id: str) -> dict[str, str]:
    return {
        "code": "research_objectives_not_ready",
        "message": (
            "The collection does not have research objectives yet. Finish "
            "processing first."
        ),
        "collection_id": collection_id,
    }


@router.get(
    "/{collection_id}/objectives",
    response_model=ObjectiveListResponse,
    summary="读取 collection research objectives",
)
async def list_collection_objectives(
    collection_id: str,
    request: Request,
) -> ObjectiveListResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.research_objective_service.list_objective_workspaces,
            collection_id,
        )
    except ResearchObjectivesNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_objectives_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ObjectiveListResponse(**payload)


@router.post(
    "/{collection_id}/objectives/{objective_id}/confirm",
    response_model=ObjectiveAnalysisResponse,
    summary="确认 research objective",
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
    return _analysis_response(payload)


@router.post(
    "/{collection_id}/objectives/{objective_id}/analysis",
    response_model=ObjectiveAnalysisResponse,
    summary="运行 research objective 深度分析",
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
    if payload["objective"].status == "queued":
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
    summary="读取 research objective 深度分析状态",
)
async def get_collection_objective_analysis(
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


@router.get(
    "/{collection_id}/objectives/{objective_id}/research-view",
    response_model=ObjectiveResearchViewResponse,
    summary="读取 objective research view",
)
async def get_collection_objective_research_view(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ObjectiveResearchViewResponse:
    try:
        payload = await run_in_threadpool(
            request.app.state.research_objective_service.get_objective_research_view,
            collection_id,
            objective_id,
        )
    except ResearchObjectiveNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "research_objective_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "objective_id": exc.objective_id,
            },
        ) from exc
    except ResearchObjectivesNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail=_research_objectives_not_ready_detail(exc.collection_id),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ObjectiveResearchViewResponse(**payload)


def _analysis_response(payload: dict) -> ObjectiveAnalysisResponse:
    objective = payload["objective"]
    understanding = payload.get("understanding")
    return ObjectiveAnalysisResponse(
        collection_id=payload["collection_id"],
        objective=(
            objective.to_workspace_record()
            if isinstance(objective, ResearchObjective)
            else objective
        ),
        understanding=(
            understanding.to_record()
            if isinstance(understanding, ResearchUnderstanding)
            else understanding
        ),
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
