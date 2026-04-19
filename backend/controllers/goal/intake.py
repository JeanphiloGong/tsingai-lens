from __future__ import annotations

from fastapi import APIRouter, HTTPException

from application.goal.brief_service import GoalService
from controllers.schemas.goal.intake import GoalIntakeRequest, GoalIntakeResponse

router = APIRouter(prefix="/goals", tags=["goals"])
goal_service = GoalService()


@router.post(
    "/intake",
    response_model=GoalIntakeResponse,
    summary="创建 Goal Brief / Intake 入口",
)
async def intake_goal(payload: GoalIntakeRequest) -> GoalIntakeResponse:
    try:
        response = goal_service.intake_goal(
            material_system=payload.material_system,
            target_property=payload.target_property,
            intent=payload.intent,
            constraints=payload.constraints,
            context=payload.context,
            max_seed_documents=payload.max_seed_documents,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoalIntakeResponse(**response)
