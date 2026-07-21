from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from application.goal.experiment_plan_service import (
    ExperimentPlanNotFoundError,
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


@router.post(
    "/{collection_id}/objectives/{objective_id}/experiment-plans",
    response_model=ExperimentPlanResponse,
    summary="Save an Objective-scoped experiment plan draft",
)
async def create_experiment_plan(
    collection_id: str,
    objective_id: str,
    payload: ExperimentPlanCreateRequest,
    request: Request,
) -> ExperimentPlanResponse:
    try:
        plan = await run_in_threadpool(
            request.app.state.experiment_plan_service.create_plan,
            collection_id=collection_id,
            objective_id=objective_id,
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
    "/{collection_id}/objectives/{objective_id}/experiment-plans",
    response_model=ExperimentPlanListResponse,
    summary="List Objective-scoped experiment plan drafts",
)
async def list_experiment_plans(
    collection_id: str,
    objective_id: str,
    request: Request,
) -> ExperimentPlanListResponse:
    plans = await run_in_threadpool(
        request.app.state.experiment_plan_service.list_plans,
        collection_id,
        objective_id,
    )
    return ExperimentPlanListResponse(
        collection_id=collection_id,
        objective_id=objective_id,
        items=[_plan_response(plan) for plan in plans],
    )


@router.patch(
    "/{collection_id}/objectives/{objective_id}/experiment-plans/{plan_id}",
    response_model=ExperimentPlanResponse,
    summary="Edit an Objective-scoped experiment plan draft",
)
async def update_experiment_plan(
    collection_id: str,
    objective_id: str,
    plan_id: str,
    payload: ExperimentPlanUpdateRequest,
    request: Request,
) -> ExperimentPlanResponse:
    try:
        plan = await run_in_threadpool(
            request.app.state.experiment_plan_service.update_plan,
            collection_id=collection_id,
            objective_id=objective_id,
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
                "objective_id": exc.objective_id,
                "plan_id": exc.plan_id,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _plan_response(plan)


def _plan_response(plan: ExperimentPlanRecord) -> ExperimentPlanResponse:
    return ExperimentPlanResponse(**plan.to_record())
