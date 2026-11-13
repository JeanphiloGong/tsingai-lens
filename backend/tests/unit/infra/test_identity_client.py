from types import SimpleNamespace
from unittest.mock import AsyncMock

import grpc
import pytest

from infra.identity.client import (
    IdentityClient,
    IdentityUnavailableError,
    SessionNotFoundError,
)
from lens.user.v1 import auth_pb2


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_resolve_session_awaits_rpc_and_maps_identity_fields():
    client = IdentityClient.__new__(IdentityClient)
    resolve = AsyncMock(return_value=auth_pb2.ResolveReply(
        user_id="researcher", email="researcher@example.test", display_name="Researcher",
    ))
    client.stub = SimpleNamespace(Resolve=resolve)

    assert await client.resolve_session("session-token") == {
        "user_id": "researcher", "email": "researcher@example.test",
        "display_name": "Researcher",
    }
    resolve.assert_awaited_once_with(
        auth_pb2.ResolveRequest(session_token="session-token"), timeout=1.0,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("code,error_type", [
    (grpc.StatusCode.UNAUTHENTICATED, SessionNotFoundError),
    (grpc.StatusCode.UNAVAILABLE, IdentityUnavailableError),
    (grpc.StatusCode.INTERNAL, IdentityUnavailableError),
])
async def test_resolve_session_translates_rpc_failure_without_exposing_details(code, error_type):
    client = IdentityClient.__new__(IdentityClient)
    client.stub = SimpleNamespace(Resolve=AsyncMock(side_effect=grpc.aio.AioRpcError(
        code, (), (), "private diagnostic",
    )))
    with pytest.raises(error_type) as raised:
        await client.resolve_session("session-token")
    assert "private diagnostic" not in str(raised.value)


@pytest.mark.anyio
async def test_resolve_session_rejects_missing_token_without_rpc():
    client = IdentityClient.__new__(IdentityClient)
    client.stub = SimpleNamespace(Resolve=AsyncMock())
    with pytest.raises(SessionNotFoundError):
        await client.resolve_session(None)
    client.stub.Resolve.assert_not_called()


@pytest.mark.anyio
async def test_resolve_session_rejects_response_without_subject():
    client = IdentityClient.__new__(IdentityClient)
    client.stub = SimpleNamespace(Resolve=AsyncMock(return_value=auth_pb2.ResolveReply()))
    with pytest.raises(IdentityUnavailableError, match="invalid_identity_response"):
        await client.resolve_session("session-token")
