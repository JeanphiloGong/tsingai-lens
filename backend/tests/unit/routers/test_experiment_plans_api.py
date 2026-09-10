from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from application.goal.experiment_plan_service import ExperimentPlanService
from controllers.goal import experiment_plans as experiment_plans_controller
from controllers.schemas.goal.experiment_plan import (
    ExperimentPlanCreateRequest,
    ExperimentPlanUpdateRequest,
)
from tests.support.experiment_plan_repository import (
    InMemoryExperimentPlanRepository,
)


class _FindingFeedbackService:
    def source_snapshot_validity(self, **_kwargs):
        return "current", []


class _CollectionService:
    async def get_collection_for_user(self, _collection_id: str, _user_id: str):
        return {"collection_id": _collection_id}


class _DenyCollectionService:
    async def get_collection_for_user(self, _collection_id: str, _user_id: str):
        raise FileNotFoundError("collection not found")


def _request(
    service: ExperimentPlanService,
    user_id: str = "expert-a",
    collection_service: object | None = None,
):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                experiment_plan_service=service,
                collection_service=collection_service or _CollectionService(),
            ),
        ),
        state=SimpleNamespace(current_user={"user_id": user_id}),
    )


def test_experiment_plan_routes_create_list_and_update_manual_plan() -> None:
    service = ExperimentPlanService(
        repository=InMemoryExperimentPlanRepository(),
        finding_feedback_service=_FindingFeedbackService(),
    )
    request = _request(service)

    created = asyncio.run(
        experiment_plans_controller.create_experiment_plan(
            "col_1",
            "objective_1",
            ExperimentPlanCreateRequest(
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
                    "acceptance_criteria": ["Direction repeats across builds."],
                    "feasibility_checks": ["Verify thermal stability."],
                    "safety_considerations": ["Review hot-surface controls."],
                    "limitations": ["Levels require expert selection."],
                },
            ),
            request,
        )
    )
    listed = asyncio.run(
        experiment_plans_controller.list_experiment_plans(
            "col_1", "objective_1", request
        )
    )
    updated = asyncio.run(
        experiment_plans_controller.update_experiment_plan(
            "col_1",
            "objective_1",
            created.plan_id,
            ExperimentPlanUpdateRequest(
                title="Edited validation matrix",
                content="Edited design with explicit controls.",
                status="ready_for_review",
                structured_plan={
                    **created.structured_plan,
                    "hypothesis": "Reviewed preheating hypothesis.",
                },
            ),
            request,
        )
    )

    assert created.status == "draft"
    assert created.created_by == "expert-a"
    assert created.source_message_id is None
    assert created.metadata == {"source": "manual"}
    assert created.plan_version == 1
    assert created.structured_plan is not None
    assert listed.items[0].plan_id == created.plan_id
    historical = asyncio.run(
        experiment_plans_controller.read_experiment_plan(
            "col_1", "objective_1", created.plan_id, request
        )
    )
    assert updated.title == "Edited validation matrix"
    assert updated.status == "ready_for_review"
    assert updated.plan_id != created.plan_id
    assert updated.plan_version == 2
    assert updated.parent_plan_id == created.plan_id
    assert updated.updated_by == "expert-a"
    assert historical.plan_id == created.plan_id

    title_only = asyncio.run(
        experiment_plans_controller.update_experiment_plan(
            "col_1",
            "objective_1",
            updated.plan_id,
            ExperimentPlanUpdateRequest(title="Title-only edit"),
            request,
        )
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


def test_experiment_plan_routes_hide_other_collection_from_non_owner() -> None:
    service = ExperimentPlanService(
        repository=InMemoryExperimentPlanRepository(),
        finding_feedback_service=_FindingFeedbackService(),
    )
    request = _request(service, collection_service=_DenyCollectionService())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            experiment_plans_controller.list_experiment_plans(
                "private-col", "objective_1", request
            )
        )

    assert exc_info.value.status_code == 404
