from __future__ import annotations

import asyncio
from types import SimpleNamespace

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


def _request(service: ExperimentPlanService, user_id: str = "expert-a"):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(experiment_plan_service=service),
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
