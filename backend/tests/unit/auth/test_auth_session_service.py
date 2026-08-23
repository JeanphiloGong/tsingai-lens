from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from application.auth import (
    AuthSessionService,
    InvalidCredentialsError,
    SessionNotFoundError,
)
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_auth_session_service_logs_in_and_resolves_user(auth_session_service):
    service = AuthSessionService(
        auth_session_service.repository,
        session_ttl_hours=1,
    )
    user = await service.create_user(
        email="reader@example.com",
        password="correct horse",
        display_name="Reader",
    )

    session = await service.login(email="reader@example.com", password="correct horse")
    resolved = await service.resolve_session(session["session_id"])

    assert session["user"] == user
    assert resolved["user_id"] == user["user_id"]
    assert resolved["email"] == "reader@example.com"
    assert "password_hash" not in resolved


async def test_auth_session_service_rejects_bad_password(auth_session_service):
    service = auth_session_service
    await service.create_user(email="reader@example.com", password="correct horse")

    with pytest.raises(InvalidCredentialsError):
        await service.login(email="reader@example.com", password="wrong")


async def test_auth_session_service_logout_revokes_session(auth_session_service):
    service = auth_session_service
    await service.create_user(email="reader@example.com", password="correct horse")
    session = await service.login(
        email="reader@example.com",
        password="correct horse",
    )

    await service.logout(session["session_id"])

    with pytest.raises(SessionNotFoundError):
        await service.resolve_session(session["session_id"])


async def test_auth_session_service_persists_only_the_bearer_token_hash(
    auth_session_service,
):
    service = auth_session_service
    await service.create_user(email="reader@example.com", password="correct horse")

    login = await service.login(
        email="reader@example.com",
        password="correct horse",
    )
    bearer_token = login["session_id"]

    stored = next(iter(service.repository.sessions_by_token_hash.values()))

    assert stored is not None
    assert stored["session_id"] != bearer_token
    assert stored["token_hash"] == sha256(bearer_token.encode("utf-8")).hexdigest()


async def test_auth_session_service_rejects_expired_session(auth_session_service):
    service = auth_session_service
    user = await service.create_user(
        email="reader@example.com",
        password="correct horse",
    )
    bearer_token = "expired-browser-token"
    now = datetime.now(timezone.utc)
    await service.repository.add_session(
        {
            "session_id": "session_expired",
            "user_id": user["user_id"],
            "token_hash": sha256(bearer_token.encode("utf-8")).hexdigest(),
            "created_at": (now - timedelta(hours=2)).isoformat(),
            "expires_at": (now - timedelta(hours=1)).isoformat(),
            "revoked_at": None,
        }
    )

    with pytest.raises(SessionNotFoundError):
        await service.resolve_session(bearer_token)
