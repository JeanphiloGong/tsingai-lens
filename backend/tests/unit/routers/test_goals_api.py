from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from exceptions import RequestInvalidException

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.goal import brief_service as goal_service
from controllers.goal import goal_routes as goals_controller
from controllers.goal.goal_routes import GoalIntakeRequest
from tests.support.collection_service import build_test_collection_service

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _request(goal_service, user_id: str = "local-user"):
    goals_controller.brief_service = goal_service
    return SimpleNamespace(state=SimpleNamespace(current_user={"user_id": user_id}))


@pytest.fixture()
def goal_services(tmp_path, *, postgres_session_factory):
    collection_service = build_test_collection_service(tmp_path / "collections")
    goal_service.collection_service = collection_service

    return collection_service, goal_service


async def test_goals_route_returns_goal_contract(goal_services):
    collection_service, goal_service = goal_services

    response = goals_controller.GoalIntakeResponse.model_validate(
        json.loads(
            (
                await goals_controller.intake_goal(
                    payload=GoalIntakeRequest(
                        material_system="PVDF",
                        target_property="adhesion strength",
                        intent="compare",
                        constraints={"substrate": "Al"},
                    ),
                    user_id=_request(goal_service).state.current_user["user_id"],
                )
            ).body
        )["data"]
    )

    collection = await collection_service.get_collection(
        response.seed_collection.collection_id
    )

    assert response.coverage_assessment.level == "direct"
    assert response.entry_recommendation.recommended_mode == "comparison"
    assert response.seed_collection.source_channels == ["upload"]
    assert response.seed_collection.seeded_document_count == 0
    assert collection["collection_id"] == response.seed_collection.collection_id
    assert collection["documents"] == []


async def test_goals_route_returns_400_for_empty_goal_signal(goal_services):
    _collection_service, goal_service = goal_services

    with pytest.raises(RequestInvalidException) as exc_info:
        goals_controller.GoalIntakeResponse.model_validate(
            json.loads(
                (
                    await goals_controller.intake_goal(
                        payload=GoalIntakeRequest(
                            material_system=None,
                            target_property=None,
                            intent="explore",
                            constraints={},
                            context=None,
                        ),
                        user_id=_request(goal_service).state.current_user["user_id"],
                    )
                ).body
            )["data"]
        )

    exc = exc_info.value
    assert exc.code == 200100
    assert "Provide at least one" in exc.message
