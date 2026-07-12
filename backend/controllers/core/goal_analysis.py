from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
from threading import Lock

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from application.core.confirmed_goal_service import ConfirmedGoalNotFoundError
from application.pipeline.goal_analysis.service import GoalAnalysisPipelineService
from controllers.schemas.core.goal_analysis import GoalAnalysisResponse
from domain.core import ConfirmedGoal, ResearchUnderstanding

router = APIRouter(prefix="/collections", tags=["goal-analysis"])
goal_analysis_service = GoalAnalysisPipelineService()
logger = logging.getLogger(__name__)
_goal_analysis_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="goal-analysis",
)
_active_goal_analysis_jobs: set[tuple[str, str]] = set()
_active_goal_analysis_jobs_lock = Lock()


@router.post(
    "/{collection_id}/goals/{goal_id}/analysis",
    response_model=GoalAnalysisResponse,
    summary="运行 confirmed goal 深度分析",
)
async def run_confirmed_goal_analysis(
    collection_id: str,
    goal_id: str,
) -> GoalAnalysisResponse:
    try:
        payload = await run_in_threadpool(
            goal_analysis_service.start_goal_analysis,
            collection_id,
            goal_id,
        )
        if _register_goal_analysis_job(collection_id, goal_id):
            future = _goal_analysis_executor.submit(
                _run_goal_analysis_blocking,
                collection_id,
                goal_id,
            )
            future.add_done_callback(
                lambda completed: _finish_goal_analysis_job(
                    collection_id,
                    goal_id,
                    completed,
                )
            )
    except ConfirmedGoalNotFoundError as exc:
        raise _goal_not_found(exc) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _analysis_response(collection_id, payload)


def _run_goal_analysis_blocking(collection_id: str, goal_id: str) -> dict:
    import asyncio

    return asyncio.run(
        goal_analysis_service.run_goal_analysis(collection_id, goal_id)
    )


def _register_goal_analysis_job(collection_id: str, goal_id: str) -> bool:
    job_key = (collection_id, goal_id)
    with _active_goal_analysis_jobs_lock:
        if job_key in _active_goal_analysis_jobs:
            return False
        _active_goal_analysis_jobs.add(job_key)
        return True


def _finish_goal_analysis_job(collection_id: str, goal_id: str, future) -> None:
    job_key = (collection_id, goal_id)
    with _active_goal_analysis_jobs_lock:
        _active_goal_analysis_jobs.discard(job_key)
    try:
        future.result()
    except Exception:  # noqa: BLE001
        logger.exception("background confirmed goal analysis failed")


@router.get(
    "/{collection_id}/goals/{goal_id}/analysis",
    response_model=GoalAnalysisResponse,
    summary="读取 confirmed goal 深度分析结果",
)
async def get_confirmed_goal_analysis(
    collection_id: str,
    goal_id: str,
) -> GoalAnalysisResponse:
    try:
        payload = await run_in_threadpool(
            goal_analysis_service.get_goal_analysis,
            collection_id,
            goal_id,
        )
    except ConfirmedGoalNotFoundError as exc:
        raise _goal_not_found(exc) from exc
    return _analysis_response(collection_id, payload)


def _analysis_response(collection_id: str, payload: dict) -> GoalAnalysisResponse:
    goal = payload["goal"]
    understanding = payload.get("understanding")
    return GoalAnalysisResponse(
        collection_id=collection_id,
        goal=goal.to_record() if isinstance(goal, ConfirmedGoal) else goal,
        understanding=(
            understanding.to_record()
            if isinstance(understanding, ResearchUnderstanding)
            else understanding
        ),
        pipeline_nodes=payload.get("pipeline_nodes") or {},
        errors=payload.get("errors") or [],
        warnings=payload.get("warnings") or [],
    )


def _goal_not_found(exc: ConfirmedGoalNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "confirmed_goal_not_found",
            "message": str(exc),
            "collection_id": exc.collection_id,
            "goal_id": exc.goal_id,
        },
    )
