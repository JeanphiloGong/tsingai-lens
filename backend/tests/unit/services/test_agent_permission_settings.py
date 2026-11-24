from datetime import datetime, timedelta, timezone

import pytest
from application.source import workspace_service
from domain.chat.permissions import AUTO_ACTIONS
from exceptions import ResourceConflictException, ResourceNotFoundException


from repositories.workspace_repository import WorkspaceRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_workspace_default_permission_round_trips_and_expands_all_actions(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
) -> None:
    workspace_service.WorkspaceRepo = WorkspaceRepository()
    service = workspace_service
    workspace = await service.create_workspace(
        "Agent settings", owner_user_id="owner",
    )
    expiry = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    saved = await service.set_agent_default_permission_for_user(
        workspace.workspace.workspace_id,
        "owner",
        mode="auto",
        actions=[],
        all_actions=True,
        expires_at=expiry,
        expected_revision=0,
    )

    assert saved["actions"] == sorted(AUTO_ACTIONS)
    assert (
        await service.get_agent_default_permission_for_user(
            workspace.workspace.workspace_id, "owner"
        )
        == saved
    )


async def test_workspace_default_permission_can_be_persistent(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
) -> None:
    workspace_service.WorkspaceRepo = WorkspaceRepository()
    service = workspace_service
    workspace = await service.create_workspace(
        "Persistent Agent settings", owner_user_id="owner",
    )

    saved = await service.set_agent_default_permission_for_user(
        workspace.workspace.workspace_id,
        "owner",
        mode="auto",
        actions=["create_finding_version"],
        expires_at=None,
        expected_revision=0,
    )

    assert saved["expires_at"] is None
    assert (
        await service.get_agent_default_permission_for_user(
            workspace.workspace.workspace_id, "owner"
        )
        == saved
    )


async def test_workspace_default_permission_hides_workspace_from_other_users(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
) -> None:
    workspace_service.WorkspaceRepo = WorkspaceRepository()
    service = workspace_service
    workspace = await service.create_workspace(
        "Private settings", owner_user_id="owner",
    )

    with pytest.raises(ResourceNotFoundException):
        await service.get_agent_default_permission_for_user(
            workspace.workspace.workspace_id, "other-user"
        )


async def test_workspace_default_permission_rejects_stale_revision(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
) -> None:
    workspace_service.WorkspaceRepo = WorkspaceRepository()
    service = workspace_service
    workspace = await service.create_workspace(
        "Concurrent settings", owner_user_id="owner",
    )
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    await service.set_agent_default_permission_for_user(
        workspace.workspace.workspace_id,
        "owner",
        mode="read_only",
        actions=[],
        expires_at=None,
        expected_revision=0,
    )
    with pytest.raises(ResourceConflictException, match="permission_revision_conflict"):
        await service.set_agent_default_permission_for_user(
            workspace.workspace.workspace_id,
            "owner",
            mode="auto",
            actions=["create_finding_version"],
            expires_at=expiry,
            expected_revision=0,
        )
