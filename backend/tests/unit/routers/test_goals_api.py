from __future__ import annotations

from infra.persistence.file import workspace_files as workspace_module
from application.source import workspace_service

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

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _request(
    monkeypatch,
    goal_service,
    user_id: str='local-user',
    *,
    workspace_files,
):
    monkeypatch.setattr(workspace_module, "Workspace", workspace_files, raising=False)
    goals_controller.brief_service = goal_service
    return SimpleNamespace(
        state=SimpleNamespace(current_user={"user_id": user_id}),
    )


@pytest.fixture()
def goal_services(tmp_path, *, postgres_session_factory):
    goal_service.workspace_service = workspace_service

    return workspace_service, goal_service


async def test_goals_route_returns_goal_contract(
    monkeypatch,
    goal_services,
    *,
    workspace_files,
):
    workspace_service, goal_service = goal_services

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
                    user_id=_request(monkeypatch, goal_service, workspace_files=workspace_files).state.current_user["user_id"],
                )
            ).body
        )["data"]
    )

    workspace = await workspace_service.get_workspace(
        response.seed_workspace.workspace_id
    )

    assert response.coverage_assessment.level == "direct"
    assert response.entry_recommendation.recommended_mode == "comparison"
    assert response.seed_workspace.source_channels == ["upload"]
    assert response.seed_workspace.seeded_document_count == 0
    assert workspace.workspace.workspace_id == response.seed_workspace.workspace_id
    assert workspace.documents == ()


async def test_goals_route_returns_400_for_empty_goal_signal(
    monkeypatch,
    goal_services,
    *,
    workspace_files,
):
    _workspace_service, goal_service = goal_services

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
                        user_id=_request(monkeypatch, goal_service, workspace_files=workspace_files).state.current_user["user_id"],
                    )
                ).body
            )["data"]
        )

    exc = exc_info.value
    assert exc.code == 200100
    assert "Provide at least one" in exc.message
