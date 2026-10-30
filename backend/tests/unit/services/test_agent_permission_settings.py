from datetime import datetime, timedelta, timezone

import pytest
from application.source import collection_service
from domain.chat.permissions import AUTO_ACTIONS
from exceptions import ResourceConflictException, ResourceNotFoundException


from repositories.collection_repository import CollectionRepository

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def collection_owner(postgres_session_factory, anyio_backend):
    from tests.support.postgres import seed_user

    await seed_user(postgres_session_factory, "owner")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_collection_default_permission_round_trips_and_expands_all_actions(
    tmp_path,
    *,
    postgres_session_factory,
    collection_workspace,
) -> None:
    collection_service.CollectionRepo = CollectionRepository()
    service = collection_service
    collection = await service.create_collection(
        "Agent settings", owner_user_id="owner",
        workspace=collection_workspace,
    )
    expiry = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    saved = await service.set_agent_default_permission_for_user(
        collection["collection_id"],
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
            collection["collection_id"], "owner"
        )
        == saved
    )


async def test_collection_default_permission_can_be_persistent(
    tmp_path,
    *,
    postgres_session_factory,
    collection_workspace,
) -> None:
    collection_service.CollectionRepo = CollectionRepository()
    service = collection_service
    collection = await service.create_collection(
        "Persistent Agent settings", owner_user_id="owner",
        workspace=collection_workspace,
    )

    saved = await service.set_agent_default_permission_for_user(
        collection["collection_id"],
        "owner",
        mode="auto",
        actions=["create_finding_version"],
        expires_at=None,
        expected_revision=0,
    )

    assert saved["expires_at"] is None
    assert (
        await service.get_agent_default_permission_for_user(
            collection["collection_id"], "owner"
        )
        == saved
    )


async def test_collection_default_permission_hides_collection_from_other_users(
    tmp_path,
    *,
    postgres_session_factory,
    collection_workspace,
) -> None:
    collection_service.CollectionRepo = CollectionRepository()
    service = collection_service
    collection = await service.create_collection(
        "Private settings", owner_user_id="owner",
        workspace=collection_workspace,
    )

    with pytest.raises(ResourceNotFoundException):
        await service.get_agent_default_permission_for_user(
            collection["collection_id"], "other-user"
        )


async def test_collection_default_permission_rejects_stale_revision(
    tmp_path,
    *,
    postgres_session_factory,
    collection_workspace,
) -> None:
    collection_service.CollectionRepo = CollectionRepository()
    service = collection_service
    collection = await service.create_collection(
        "Concurrent settings", owner_user_id="owner",
        workspace=collection_workspace,
    )
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    await service.set_agent_default_permission_for_user(
        collection["collection_id"],
        "owner",
        mode="read_only",
        actions=[],
        expires_at=None,
        expected_revision=0,
    )
    with pytest.raises(ResourceConflictException, match="permission_revision_conflict"):
        await service.set_agent_default_permission_for_user(
            collection["collection_id"],
            "owner",
            mode="auto",
            actions=["create_finding_version"],
            expires_at=expiry,
            expected_revision=0,
        )
