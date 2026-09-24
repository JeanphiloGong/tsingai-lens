from datetime import datetime, timedelta, timezone

import pytest

from application.source.collection_service import CollectionService
from domain.chat.permissions import AUTO_ACTIONS
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.memory import MemoryCollectionRepository


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_collection_default_permission_round_trips_and_expands_all_actions(tmp_path) -> None:
    service = CollectionService(
        repository=MemoryCollectionRepository(),
        workspace=FileCollectionWorkspace(tmp_path / "collections"),
    )
    collection = await service.create_collection("Agent settings", owner_user_id="owner")
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
    assert await service.get_agent_default_permission_for_user(
        collection["collection_id"], "owner"
    ) == saved


async def test_collection_default_permission_hides_collection_from_other_users(tmp_path) -> None:
    service = CollectionService(
        repository=MemoryCollectionRepository(),
        workspace=FileCollectionWorkspace(tmp_path / "collections"),
    )
    collection = await service.create_collection("Private settings", owner_user_id="owner")

    with pytest.raises(FileNotFoundError):
        await service.get_agent_default_permission_for_user(
            collection["collection_id"], "other-user"
        )


async def test_collection_default_permission_rejects_stale_revision(tmp_path) -> None:
    service = CollectionService(
        repository=MemoryCollectionRepository(),
        workspace=FileCollectionWorkspace(tmp_path / "collections"),
    )
    collection = await service.create_collection("Concurrent settings", owner_user_id="owner")
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    await service.set_agent_default_permission_for_user(
        collection["collection_id"],
        "owner",
        mode="read_only",
        actions=[],
        expires_at=None,
        expected_revision=0,
    )
    with pytest.raises(ValueError, match="permission_revision_conflict"):
        await service.set_agent_default_permission_for_user(
            collection["collection_id"],
            "owner",
            mode="auto",
            actions=["create_finding_version"],
            expires_at=expiry,
            expected_revision=0,
        )
