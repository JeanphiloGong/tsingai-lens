from __future__ import annotations

from typing import Annotated, Any, Literal

from application.goal import experiment_plan_service
from application.goal.research_plan_contract import ResearchPlanStructure
from controllers.dependencies.auth import get_current_user_id
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from utils.response import ApiResponse, make_api_response

ExperimentPlanStatus = Literal["draft", "ready_for_review", "archived"]
ExperimentPlanSourceLinkKind = Literal["document", "evidence"]


class ExperimentPlanSourceLink(BaseModel):
    kind: ExperimentPlanSourceLinkKind
    label: str = Field(..., min_length=1, max_length=80)
    href: str = Field(..., min_length=1, max_length=2000)


class ExperimentPlanCreateRequest(BaseModel):
    """Save one manual Objective-scoped experiment plan draft."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(..., min_length=1, max_length=400)
    content: str = Field(..., min_length=1, max_length=20000)
    structured_plan: ResearchPlanStructure | None = None


class ExperimentPlanUpdateRequest(BaseModel):
    """Edit a saved experiment plan draft."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=400)
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    status: ExperimentPlanStatus | None = None
    structured_plan: ResearchPlanStructure | None = None

    @model_validator(mode="after")
    def require_one_change(self) -> "ExperimentPlanUpdateRequest":
        if (
            self.title is None
            and self.content is None
            and self.status is None
            and self.structured_plan is None
        ):
            raise ValueError("experiment plan PATCH requires at least one field")
        return self


class ExperimentPlanResponse(BaseModel):
    plan_id: str
    collection_id: str
    objective_id: str
    title: str
    content: str
    status: ExperimentPlanStatus
    source_message_id: str | None = None
    source_links: list[ExperimentPlanSourceLink] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: str
    updated_at: str
    plan_version: int = Field(default=1, ge=1)
    parent_plan_id: str | None = None
    structured_plan: dict[str, Any] | None = None
    updated_by: str | None = None


class ExperimentPlanListResponse(BaseModel):
    collection_id: str
    objective_id: str
    items: list[ExperimentPlanResponse] = Field(default_factory=list)


experiment_plan_router = APIRouter(prefix="/collections", tags=["experiment-plans"])


@experiment_plan_router.post(
    "/{collection_id}/objectives/{objective_id}/experiment-plans",
    response_model=ApiResponse[ExperimentPlanResponse],
    summary="Save an Objective-scoped experiment plan draft",
)
async def create_experiment_plan(
    collection_id: str,
    objective_id: str,
    payload: ExperimentPlanCreateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    plan = await experiment_plan_service.create_plan(
        collection_id=collection_id,
        objective_id=objective_id,
        title=payload.title,
        content=payload.content,
        structured_plan=(
            payload.structured_plan.model_dump()
            if payload.structured_plan is not None
            else None
        ),
        created_by=user_id,
    )
    return make_api_response(
        data=ExperimentPlanResponse.model_validate(plan, from_attributes=True)
    )


@experiment_plan_router.get(
    "/{collection_id}/objectives/{objective_id}/experiment-plans",
    response_model=ApiResponse[ExperimentPlanListResponse],
    summary="List Objective-scoped experiment plan drafts",
)
async def list_experiment_plans(
    collection_id: str,
    objective_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    plans = await experiment_plan_service.list_plans(
        collection_id,
        objective_id,
        user_id=user_id,
    )
    return make_api_response(
        data=ExperimentPlanListResponse(
            collection_id=collection_id,
            objective_id=objective_id,
            items=[
                ExperimentPlanResponse.model_validate(plan, from_attributes=True)
                for plan in plans
            ],
        )
    )


@experiment_plan_router.get(
    "/{collection_id}/objectives/{objective_id}/experiment-plans/{plan_id}",
    response_model=ApiResponse[ExperimentPlanResponse],
    summary="Read one experiment plan revision",
)
async def read_experiment_plan(
    collection_id: str,
    objective_id: str,
    plan_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    plan = await experiment_plan_service.read_plan(
        collection_id,
        objective_id,
        plan_id,
        user_id=user_id,
    )
    return make_api_response(
        data=ExperimentPlanResponse.model_validate(plan, from_attributes=True)
    )


@experiment_plan_router.patch(
    "/{collection_id}/objectives/{objective_id}/experiment-plans/{plan_id}",
    response_model=ApiResponse[ExperimentPlanResponse],
    summary="Edit an Objective-scoped experiment plan draft",
)
async def update_experiment_plan(
    collection_id: str,
    objective_id: str,
    plan_id: str,
    payload: ExperimentPlanUpdateRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    plan = await experiment_plan_service.update_plan(
        collection_id=collection_id,
        objective_id=objective_id,
        plan_id=plan_id,
        title=payload.title,
        content=payload.content,
        status=payload.status,
        structured_plan=(
            payload.structured_plan.model_dump()
            if payload.structured_plan is not None
            else None
        ),
        updated_by=user_id,
    )
    return make_api_response(
        data=ExperimentPlanResponse.model_validate(plan, from_attributes=True)
    )
