from __future__ import annotations
from application.source import workspace_service

import pytest
from application.goal import brief_service as goal_service
from exceptions import RequestInvalidException

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_goal_service_creates_seed_workspace_and_contract(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
):
    goal_service.workspace_service = workspace_service
    service = goal_service

    payload = await service.intake_goal(
        material_system="LiFePO4",
        target_property="rate capability",
        intent="compare",
        constraints={"temperature": "298 K"},
        context="Focus on battery cathode studies.",
        max_seed_documents=24,
    )

    workspace_id = payload["seed_workspace"]["workspace_id"]
    workspace = await workspace_service.get_workspace(workspace_id)

    assert (
        payload["research_brief"]["objective"] == "Assess rate capability for LiFePO4."
    )
    assert payload["coverage_assessment"]["level"] == "direct"
    assert payload["entry_recommendation"]["recommended_mode"] == "comparison"
    assert payload["seed_workspace"]["created"] is True
    assert payload["seed_workspace"]["seeded_document_count"] == 0
    assert payload["seed_workspace"]["source_channels"] == ["upload"]
    assert set(payload["seed_workspace"]) == {
        "workspace_id",
        "name",
        "created",
        "seeded_document_count",
        "source_channels",
    }
    assert workspace.workspace.workspace_id == workspace_id
    assert workspace.workspace.description == "Assess rate capability for LiFePO4."
    assert workspace.documents == ()


async def test_goal_service_rejects_empty_goal_signal(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
):
    goal_service.workspace_service = workspace_service
    service = goal_service

    with pytest.raises(RequestInvalidException) as exc_info:
        await service.intake_goal(
            material_system=None,
            target_property=None,
            intent="explore",
            constraints={},
            context=None,
            max_seed_documents=30,
        )

    assert "Provide at least one" in str(exc_info.value)
