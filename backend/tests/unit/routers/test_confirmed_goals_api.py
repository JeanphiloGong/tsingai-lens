from __future__ import annotations

import asyncio

from controllers.core import confirmed_goals as goal_controller
from controllers.schemas.core.confirmed_goals import ConfirmedGoalCreateRequest
from domain.core import ConfirmedGoal


class FakeConfirmedGoalService:
    def __init__(self) -> None:
        self.created = None
        self.goals = (
            ConfirmedGoal.from_mapping(
                {
                    "collection_id": "col-1",
                    "question": "How does laser power affect density?",
                    "source_type": "user_input",
                    "material_hints": ["AlSi10Mg"],
                    "process_hints": ["LPBF"],
                    "property_hints": ["density"],
                    "status": "pending",
                    "created_at": "2026-06-24T01:00:00+00:00",
                    "updated_at": "2026-06-24T01:00:00+00:00",
                }
            ),
        )

    def create_goal(self, **kwargs):  # noqa: ANN003
        self.created = kwargs
        return self.goals[0]

    def list_goals(self, collection_id: str):
        self.listed_collection_id = collection_id
        return self.goals

    def get_goal(self, collection_id: str, goal_id: str):
        self.get_args = (collection_id, goal_id)
        return self.goals[0]


def test_confirmed_goal_route_creates_goal_from_question(monkeypatch):
    service = FakeConfirmedGoalService()
    monkeypatch.setattr(goal_controller, "confirmed_goal_service", service)

    response = asyncio.run(
        goal_controller.create_confirmed_goal(
            "col-1",
            ConfirmedGoalCreateRequest(
                question="How does laser power affect density?",
                source_type="user_input",
                material_hints=["AlSi10Mg"],
                process_hints=["LPBF"],
                property_hints=["density"],
            ),
        )
    )

    assert response.collection_id == "col-1"
    assert response.question == "How does laser power affect density?"
    assert response.status == "pending"
    assert service.created == {
        "collection_id": "col-1",
        "question": "How does laser power affect density?",
        "source_type": "user_input",
        "material_hints": ["AlSi10Mg"],
        "process_hints": ["LPBF"],
        "property_hints": ["density"],
        "source_objective_id": None,
    }


def test_confirmed_goal_route_lists_collection_goals(monkeypatch):
    service = FakeConfirmedGoalService()
    monkeypatch.setattr(goal_controller, "confirmed_goal_service", service)

    response = asyncio.run(goal_controller.list_confirmed_goals("col-1"))

    assert response.collection_id == "col-1"
    assert response.goals[0].source_type == "user_input"
    assert service.listed_collection_id == "col-1"


def test_confirmed_goal_route_reads_one_goal(monkeypatch):
    service = FakeConfirmedGoalService()
    monkeypatch.setattr(goal_controller, "confirmed_goal_service", service)

    response = asyncio.run(goal_controller.get_confirmed_goal("col-1", "goal-1"))

    assert response.question == "How does laser power affect density?"
    assert service.get_args == ("col-1", "goal-1")
