from __future__ import annotations

import asyncio

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.source.collection_service import CollectionService
from application.goal.brief_service import GoalService
from controllers.goal import intake as goals_controller
from controllers.schemas.goal.intake import GoalIntakeRequest


@pytest.fixture()
def goal_services(monkeypatch, tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    goal_service = GoalService(collection_service)

    monkeypatch.setattr(goals_controller, "goal_service", goal_service)

    return collection_service, goal_service


def test_goals_route_returns_goal_contract(goal_services):
    collection_service, _goal_service = goal_services

    response = asyncio.run(
        goals_controller.intake_goal(
            GoalIntakeRequest(
                material_system="PVDF",
                target_property="adhesion strength",
                intent="compare",
                constraints={"substrate": "Al"},
            )
        )
    )

    collection = collection_service.get_collection(response.seed_collection.collection_id)

    assert response.coverage_assessment.level == "direct"
    assert response.entry_recommendation.recommended_mode == "comparison"
    assert response.seed_collection.source_channels == ["upload"]
    assert response.seed_collection.handoff_id.startswith("handoff_")
    assert response.seed_collection.handoff_status == "awaiting_source_material"
    assert collection["collection_id"] == response.seed_collection.collection_id


def test_goals_route_returns_400_for_empty_goal_signal(goal_services):
    _collection_service, _goal_service = goal_services

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            goals_controller.intake_goal(
                GoalIntakeRequest(
                    material_system=None,
                    target_property=None,
                    intent="explore",
                    constraints={},
                    context=None,
                )
            )
        )

    exc = exc_info.value
    assert exc.status_code == 400
    assert "至少提供" in str(exc.detail)
