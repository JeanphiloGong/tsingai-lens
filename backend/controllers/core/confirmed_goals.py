from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from application.core.confirmed_goal_service import (
    ConfirmedGoalNotFoundError,
    ConfirmedGoalService,
)
from controllers.schemas.core.confirmed_goals import (
    ConfirmedGoalCreateRequest,
    ConfirmedGoalListResponse,
    ConfirmedGoalResponse,
)
from domain.core import ConfirmedGoal

router = APIRouter(prefix="/collections", tags=["confirmed-goals"])
confirmed_goal_service = ConfirmedGoalService()


@router.post(
    "/{collection_id}/goals",
    response_model=ConfirmedGoalResponse,
    summary="创建 confirmed research goal",
)
async def create_confirmed_goal(
    collection_id: str,
    payload: ConfirmedGoalCreateRequest,
) -> ConfirmedGoalResponse:
    goal = await run_in_threadpool(
        confirmed_goal_service.create_goal,
        collection_id=collection_id,
        question=payload.question,
        source_type=payload.source_type,
        material_hints=payload.material_hints,
        process_hints=payload.process_hints,
        property_hints=payload.property_hints,
        source_objective_id=payload.source_objective_id,
    )
    return _goal_response(goal)


@router.get(
    "/{collection_id}/goals",
    response_model=ConfirmedGoalListResponse,
    summary="读取 collection confirmed goals",
)
async def list_confirmed_goals(collection_id: str) -> ConfirmedGoalListResponse:
    goals = await run_in_threadpool(
        confirmed_goal_service.list_goals,
        collection_id,
    )
    return ConfirmedGoalListResponse(
        collection_id=collection_id,
        goals=[_goal_response(goal) for goal in goals],
    )


@router.get(
    "/{collection_id}/goals/{goal_id}",
    response_model=ConfirmedGoalResponse,
    summary="读取 confirmed goal",
)
async def get_confirmed_goal(
    collection_id: str,
    goal_id: str,
) -> ConfirmedGoalResponse:
    try:
        goal = await run_in_threadpool(
            confirmed_goal_service.get_goal,
            collection_id,
            goal_id,
        )
    except ConfirmedGoalNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "confirmed_goal_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "goal_id": exc.goal_id,
            },
        ) from exc
    return _goal_response(goal)


def _goal_response(goal: ConfirmedGoal) -> ConfirmedGoalResponse:
    return ConfirmedGoalResponse(**goal.to_record())
