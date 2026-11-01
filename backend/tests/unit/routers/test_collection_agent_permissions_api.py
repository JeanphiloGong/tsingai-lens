import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import controllers.source.collection_routes as routes
import pytest
from controllers.source.collection_routes import (
    CollectionAgentPermissionRequest,
    get_collection_agent_permission,
    set_collection_agent_permission,
)
from exceptions import ResourceNotFoundException


def _request(service, user_id: str = "owner") -> SimpleNamespace:
    routes.collection_service = service
    return SimpleNamespace(state=SimpleNamespace(current_user={"user_id": user_id}))


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
            raise ResourceNotFoundException("collection not found")
        return self.saved

    async def set_agent_default_permission_for_user(
        self, collection_id, user_id, **changes
    ):
        assert collection_id == "col-1"
        if user_id != "owner":
            raise ResourceNotFoundException("collection not found")
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
    read = asyncio.run(
        get_collection_agent_permission(
            collection_id="col-1", user_id=request.state.current_user["user_id"]
        )
    )
    updated = asyncio.run(
        set_collection_agent_permission(
            collection_id="col-1",
            payload=CollectionAgentPermissionRequest(
                mode="auto",
                all_actions=True,
                expires_at=(
                    datetime.now(timezone.utc) + timedelta(hours=2)
                ).isoformat(),
                expected_revision=0,
            ),
            user_id=request.state.current_user["user_id"],
        )
    )

    read = routes.CollectionAgentPermissionResponse.model_validate(json.loads(read.body)["data"])
    updated = routes.CollectionAgentPermissionResponse.model_validate(json.loads(updated.body)["data"])
    assert read.revision == 0
    assert updated.mode == "auto"
    assert updated.revision == 1


def test_collection_permission_endpoint_hides_other_owner() -> None:
    with pytest.raises(ResourceNotFoundException) as error:
        asyncio.run(
            get_collection_agent_permission(
                collection_id="col-1",
                user_id=_request(_Service(), "other").state.current_user["user_id"],
            )
        )

    assert error.value.code == 200201
