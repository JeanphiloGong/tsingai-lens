from __future__ import annotations

import asyncio
import json
from types import ModuleType, SimpleNamespace

import pytest
from application.goal import experiment_plan_service
from controllers.goal import experiment_plan_routes as experiment_plans_controller
from controllers.goal.experiment_plan_routes import (
    ExperimentPlanCreateRequest,
    ExperimentPlanUpdateRequest,
)
from exceptions import ResourceNotFoundException
from pydantic import ValidationError
from repositories.experiment_plan_repository import ExperimentPlanRepository


class _FindingFeedbackService:
    def source_snapshot_validity(self, **_kwargs):
        return "current", []


class _CollectionService:
    async def get_collection_for_user(self, _collection_id: str, _user_id: str):
        return {"collection_id": _collection_id}


class _DenyCollectionService:
    async def get_collection_for_user(self, _collection_id: str, _user_id: str):
        raise ResourceNotFoundException("collection not found")


def _request(
    service: ModuleType,
    user_id: str = "expert-a",
    collection_service: object | None = None,
):
    experiment_plans_controller.experiment_plan_service = service
    service.collection_service = collection_service or _CollectionService()
    return SimpleNamespace(state=SimpleNamespace(current_user={"user_id": user_id}))


def test_stale_plan_update_returns_http_business_conflict_without_another_revision(
    postgres_session_factory,
) -> None:
    from controllers.dependencies.auth import get_current_user_id
    from controllers.exception_router import general_exception_handler, project_exception_handler
    from exceptions import ProjectException
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tests.support.postgres import seed_objective, seed_user

    asyncio.run(seed_objective(postgres_session_factory, "col_1", "objective_1"))
    asyncio.run(seed_user(postgres_session_factory, "expert-a"))
    repository = ExperimentPlanRepository()
    experiment_plan_service.ExperimentPlanRepo = repository
    experiment_plan_service.finding_feedback_service = _FindingFeedbackService()
    _request(experiment_plan_service)
    app = FastAPI()
    app.include_router(experiment_plans_controller.experiment_plan_router, prefix="/api/v1")
    app.add_exception_handler(ProjectException, project_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    app.dependency_overrides[get_current_user_id] = lambda: "expert-a"
    url = "/api/v1/collections/col_1/objectives/objective_1/experiment-plans"

    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post(url, json={
            "title": "LPBF porosity follow-up", "content": "Compare laser power with a fixed powder batch.",
        }).json()["data"]
        parent_url = f"{url}/{created['plan_id']}"
        accepted = client.patch(parent_url, json={"content": "Use independent builds for each power level."})
        rejected = client.patch(parent_url, json={"content": "Overwrite the earlier version."})

    assert accepted.json()["code"] == 200
    assert rejected.status_code == 200
    assert rejected.json()["code"] == 200204
    assert rejected.json()["data"]["code"] == "experiment_plan_revision_superseded"
    assert rejected.json()["data"]["parent_plan_id"] == created["plan_id"]
    plans = asyncio.run(repository.list_plans("col_1", "objective_1"))
    assert len(plans) == 1
    assert plans[0].plan_id == accepted.json()["data"]["plan_id"]
    assert plans[0].content == "Use independent builds for each power level."


def test_experiment_plan_routes_create_list_and_update_manual_plan(
    *, postgres_session_factory
) -> None:
    from tests.support.postgres import seed_objective, seed_user

    asyncio.run(seed_objective(postgres_session_factory, "col_1", "objective_1"))
    asyncio.run(seed_user(postgres_session_factory, "expert-a"))
    experiment_plan_service.ExperimentPlanRepo = ExperimentPlanRepository()
    experiment_plan_service.finding_feedback_service = _FindingFeedbackService()
    service = experiment_plan_service
    request = _request(service)

    created = experiment_plans_controller.ExperimentPlanResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    experiment_plans_controller.create_experiment_plan(
                        collection_id="col_1",
                        objective_id="objective_1",
                        payload=ExperimentPlanCreateRequest(
                            title="Preheating validation matrix",
                            content="Expert-authored validation design.",
                            structured_plan={
                                "hypothesis": "Preheating changes elongation.",
                                "variables": [
                                    {
                                        "name": "preheating temperature",
                                        "role": "independent",
                                        "planned_values": ["expert-selected levels"],
                                        "basis": "expert_selection_required",
                                        "basis_evidence_ids": [],
                                    }
                                ],
                                "controls": ["Include an unheated reference."],
                                "fixed_conditions": ["Hold alloy state fixed."],
                                "measurements": ["Measure elongation."],
                                "replication": "Use independent builds.",
                                "analysis_method": "Estimate the response with uncertainty.",
                                "acceptance_criteria": [
                                    "Direction repeats across builds."
                                ],
                                "feasibility_checks": ["Verify thermal stability."],
                                "safety_considerations": [
                                    "Review hot-surface controls."
                                ],
                                "limitations": ["Levels require expert selection."],
                            },
                        ),
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    listed = experiment_plans_controller.ExperimentPlanListResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    experiment_plans_controller.list_experiment_plans(
                        collection_id="col_1",
                        objective_id="objective_1",
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    updated = experiment_plans_controller.ExperimentPlanResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    experiment_plans_controller.update_experiment_plan(
                        collection_id="col_1",
                        objective_id="objective_1",
                        plan_id=created.plan_id,
                        payload=ExperimentPlanUpdateRequest(
                            title="Edited validation matrix",
                            content="Edited design with explicit controls.",
                            status="ready_for_review",
                            structured_plan={
                                **created.structured_plan,
                                "hypothesis": "Reviewed preheating hypothesis.",
                            },
                        ),
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )

    assert created.status == "draft"
    assert created.created_by == "expert-a"
    assert created.source_message_id is None
    assert created.metadata == {"source": "manual"}
    assert created.plan_version == 1
    assert created.structured_plan is not None
    assert listed.items[0].plan_id == created.plan_id
    historical = experiment_plans_controller.ExperimentPlanResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    experiment_plans_controller.read_experiment_plan(
                        collection_id="col_1",
                        objective_id="objective_1",
                        plan_id=created.plan_id,
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    assert updated.title == "Edited validation matrix"
    assert updated.status == "ready_for_review"
    assert updated.plan_id != created.plan_id
    assert updated.plan_version == 2
    assert updated.parent_plan_id == created.plan_id
    assert updated.updated_by == "expert-a"
    assert historical.plan_id == created.plan_id

    title_only = experiment_plans_controller.ExperimentPlanResponse.model_validate(
        json.loads(
            (
                asyncio.run(
                    experiment_plans_controller.update_experiment_plan(
                        collection_id="col_1",
                        objective_id="objective_1",
                        plan_id=updated.plan_id,
                        payload=ExperimentPlanUpdateRequest(title="Title-only edit"),
                        user_id=request.state.current_user["user_id"],
                    )
                )
            ).body
        )["data"]
    )
    assert title_only.title == "Title-only edit"
    assert title_only.content == updated.content
    assert title_only.status == updated.status
    assert historical.plan_version == 1


def test_experiment_plan_create_contract_rejects_chat_message_provenance() -> None:
    with pytest.raises(ValidationError):
        ExperimentPlanCreateRequest.model_validate(
            {
                "title": "Unvalidated Agent plan",
                "content": "General chat prose.",
                "source_message_id": "msg_chat",
            }
        )


def test_experiment_plan_update_contract_allows_partial_patch() -> None:
    payload = ExperimentPlanUpdateRequest.model_validate({"title": "Renamed"})

    assert payload.title == "Renamed"
    assert payload.content is None
    assert payload.status is None
    assert payload.structured_plan is None


def test_experiment_plan_routes_hide_other_collection_from_non_owner(
    *, postgres_session_factory
) -> None:
    experiment_plan_service.ExperimentPlanRepo = ExperimentPlanRepository()
    experiment_plan_service.finding_feedback_service = _FindingFeedbackService()
    service = experiment_plan_service
    request = _request(service, collection_service=_DenyCollectionService())

    with pytest.raises(ResourceNotFoundException) as exc_info:
        experiment_plans_controller.ExperimentPlanListResponse.model_validate(
            json.loads(
                (
                    asyncio.run(
                        experiment_plans_controller.list_experiment_plans(
                            collection_id="private-col",
                            objective_id="objective_1",
                            user_id=request.state.current_user["user_id"],
                        )
                    )
                ).body
            )["data"]
        )

    assert exc_info.value.code == 200201
