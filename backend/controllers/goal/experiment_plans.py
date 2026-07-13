from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from application.goal.experiment_plan_service import (
    ExperimentPlanNotFoundError,
    ExperimentPlanService,
)
from controllers.dependencies.auth import current_user_id
from controllers.schemas.goal.experiment_plan import (
    ExperimentPlanCreateRequest,
    ExperimentPlanListResponse,
    ExperimentPlanResponse,
    ExperimentPlanUpdateRequest,
)
from domain.goal import ExperimentPlanRecord

router = APIRouter(prefix="/collections", tags=["experiment-plans"])
experiment_plan_service = ExperimentPlanService()


@router.post(
    "/{collection_id}/goals/{goal_id}/experiment-plans",
    response_model=ExperimentPlanResponse,
    summary="Save a goal-scoped experiment plan draft",
)
async def create_experiment_plan(
    collection_id: str,
    goal_id: str,
    payload: ExperimentPlanCreateRequest,
    request: Request,
) -> ExperimentPlanResponse:
    try:
        plan = await run_in_threadpool(
            experiment_plan_service.create_plan,
            collection_id=collection_id,
            goal_id=goal_id,
            title=payload.title,
            content=payload.content,
            source_message_id=payload.source_message_id,
            source_links=[link.model_dump() for link in payload.source_links],
            metadata=payload.metadata,
            created_by=current_user_id(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _plan_response(plan)


@router.get(
    "/{collection_id}/goals/{goal_id}/experiment-plans",
    response_model=ExperimentPlanListResponse,
    summary="List goal-scoped experiment plan drafts",
)
async def list_experiment_plans(
    collection_id: str,
    goal_id: str,
) -> ExperimentPlanListResponse:
    plans = await run_in_threadpool(
        experiment_plan_service.list_plans,
        collection_id,
        goal_id,
    )
    return ExperimentPlanListResponse(
        collection_id=collection_id,
        goal_id=goal_id,
        items=[_plan_response(plan) for plan in plans],
    )


@router.patch(
    "/{collection_id}/goals/{goal_id}/experiment-plans/{plan_id}",
    response_model=ExperimentPlanResponse,
    summary="Edit a goal-scoped experiment plan draft",
)
async def update_experiment_plan(
    collection_id: str,
    goal_id: str,
    plan_id: str,
    payload: ExperimentPlanUpdateRequest,
) -> ExperimentPlanResponse:
    try:
        plan = await run_in_threadpool(
            experiment_plan_service.update_plan,
            collection_id=collection_id,
            goal_id=goal_id,
            plan_id=plan_id,
            title=payload.title,
            content=payload.content,
            status=payload.status,
        )
    except ExperimentPlanNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "experiment_plan_not_found",
                "message": str(exc),
                "collection_id": exc.collection_id,
                "goal_id": exc.goal_id,
                "plan_id": exc.plan_id,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _plan_response(plan)


def _plan_response(plan: ExperimentPlanRecord) -> ExperimentPlanResponse:
    return ExperimentPlanResponse(**plan.to_record())
