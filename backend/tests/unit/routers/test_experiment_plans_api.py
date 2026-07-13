from __future__ import annotations

import asyncio
from types import SimpleNamespace

from application.goal.experiment_plan_service import ExperimentPlanService
from controllers.goal import experiment_plans as experiment_plans_controller
from controllers.schemas.goal.experiment_plan import (
    ExperimentPlanCreateRequest,
    ExperimentPlanUpdateRequest,
)
from infra.persistence.sqlite import (
    SqliteExperimentPlanRepository,
    SqliteGoalSessionRepository,
)


def _request(user_id: str = "expert-a"):
    return SimpleNamespace(state=SimpleNamespace(current_user={"user_id": user_id}))


def _write_goal_message(repository: SqliteGoalSessionRepository) -> None:
    repository.write_session(
        {
            "session_id": "session_1",
            "user_id": "expert-a",
            "collection_id": "col_1",
            "focused_material_id": None,
            "focused_paper_id": None,
            "focused_objective_id": None,
            "focused_goal_id": "goal_1",
            "goal_text": None,
            "goal_brief_json": {},
            "answer_mode": "hybrid",
            "rolling_summary": "",
            "last_evidence_ids": [],
            "last_material_ids": [],
            "last_paper_ids": [],
            "collection_data_version": None,
            "created_at": "2026-07-13T00:00:00+00:00",
            "updated_at": "2026-07-13T00:00:00+00:00",
        }
    )
    repository.write_messages(
        "session_1",
        [
            {
                "message_id": "msg_1",
                "session_id": "session_1",
                "role": "assistant",
                "content": "Compare room-temperature and 150 C preheated LPBF builds.",
                "answer": "Compare room-temperature and 150 C preheated LPBF builds.",
                "source_mode": "collection_grounded",
                "used_evidence_ids": ["ev_1"],
                "warnings": [],
                "links": {},
                "source_links": [
                    {
                        "kind": "evidence",
                        "label": "Source 1",
                        "href": "/collections/col_1/documents/paper-a?evidence_id=ev_1",
                    }
                ],
                "created_at": "2026-07-13T00:01:00+00:00",
            }
        ],
    )


def test_experiment_plan_routes_create_list_and_update(tmp_path, monkeypatch):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(goal_session_repository)
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )
    monkeypatch.setattr(
        experiment_plans_controller,
        "experiment_plan_service",
        service,
    )

    created = asyncio.run(
        experiment_plans_controller.create_experiment_plan(
            "col_1",
            "goal_1",
            ExperimentPlanCreateRequest(
                title="Preheating validation matrix",
                content="Compare room-temperature and 150 C preheated LPBF builds.",
                source_message_id="msg_1",
                source_links=[
                    {
                        "kind": "evidence",
                        "label": "Source 1",
                        "href": "/collections/col_1/documents/paper-a?evidence_id=ev_1",
                    }
                ],
            ),
            _request(),
        )
    )
    listed = asyncio.run(
        experiment_plans_controller.list_experiment_plans("col_1", "goal_1")
    )
    updated = asyncio.run(
        experiment_plans_controller.update_experiment_plan(
            "col_1",
            "goal_1",
            created.plan_id,
            ExperimentPlanUpdateRequest(
                title="Edited validation matrix",
                content="Add a no-preheat control and repeat tensile testing.",
                status="ready_for_review",
            ),
        )
    )

    assert created.status == "draft"
    assert created.created_by == "expert-a"
    assert created.source_links[0].label == "Source 1"
    assert listed.items[0].plan_id == created.plan_id
    assert updated.title == "Edited validation matrix"
    assert updated.status == "ready_for_review"
