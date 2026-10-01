import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from controllers.source.collections import (
    CollectionAgentPermissionRequest,
    get_collection_agent_permission,
    set_collection_agent_permission,
)


def _request(service, user_id: str = "owner") -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(collection_service=service)),
        state=SimpleNamespace(current_user={"user_id": user_id}),
    )


class _Service:
    def __init__(self) -> None:
        self.saved = {
            "mode": "confirm",
            "actions": [],
            "expires_at": None,
            "revision": 0,
        }

    async def get_agent_default_permission_for_user(self, collection_id, user_id):
        assert collection_id == "col-1"
        if user_id != "owner":
            raise FileNotFoundError("collection not found")
        return self.saved

    async def set_agent_default_permission_for_user(self, collection_id, user_id, **changes):
        assert collection_id == "col-1"
        if user_id != "owner":
            raise FileNotFoundError("collection not found")
        assert changes["all_actions"] is True
        self.saved = {
            "mode": "auto",
            "actions": ["create_finding_version"],
            "expires_at": changes["expires_at"],
            "revision": 1,
        }
        return self.saved


def test_collection_permission_endpoint_reads_and_expands_all_actions() -> None:
    service = _Service()
    request = _request(service)
    read = asyncio.run(get_collection_agent_permission("col-1", request))
    updated = asyncio.run(
        set_collection_agent_permission(
            "col-1",
            CollectionAgentPermissionRequest(
                mode="auto",
                all_actions=True,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
                expected_revision=0,
            ),
            request,
        )
    )

    assert read.revision == 0
    assert updated.mode == "auto"
    assert updated.revision == 1


def test_collection_permission_endpoint_hides_other_owner() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            get_collection_agent_permission("col-1", _request(_Service(), "other"))
        )

    assert error.value.status_code == 404
