from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
from sqlalchemy import select

from application.auth import (
    AuthSessionService,
    InvalidCredentialsError,
    SessionNotFoundError,
)
from infra.persistence.postgres.models.auth import AuthSession


def test_auth_session_service_logs_in_and_resolves_user(auth_session_service):
    service = AuthSessionService(
        auth_session_service.repository,
        session_ttl_hours=1,
    )
    user = service.create_user(
        email="reader@example.com",
        password="correct horse",
        display_name="Reader",
    )

    session = service.login(email="reader@example.com", password="correct horse")
    resolved = service.resolve_session(session["session_id"])

    assert session["user"] == user
    assert resolved["user_id"] == user["user_id"]
    assert resolved["email"] == "reader@example.com"
    assert "password_hash" not in resolved


def test_auth_session_service_rejects_bad_password(auth_session_service):
    service = auth_session_service
    service.create_user(email="reader@example.com", password="correct horse")

    with pytest.raises(InvalidCredentialsError):
        service.login(email="reader@example.com", password="wrong")


def test_auth_session_service_logout_revokes_session(auth_session_service):
    service = auth_session_service
    service.create_user(email="reader@example.com", password="correct horse")
    session = service.login(email="reader@example.com", password="correct horse")

    service.logout(session["session_id"])

    with pytest.raises(SessionNotFoundError):
        service.resolve_session(session["session_id"])


def test_auth_session_service_persists_only_the_bearer_token_hash(
    auth_session_service,
):
    service = auth_session_service
    service.create_user(email="reader@example.com", password="correct horse")

    login = service.login(email="reader@example.com", password="correct horse")
    bearer_token = login["session_id"]

    with service.repository.session_factory() as database_session:
        stored = database_session.scalar(select(AuthSession))

    assert stored is not None
    assert stored.session_id != bearer_token
    assert stored.token_hash == sha256(bearer_token.encode("utf-8")).hexdigest()


def test_auth_session_service_rejects_expired_session(auth_session_service):
    service = auth_session_service
    user = service.create_user(
        email="reader@example.com",
        password="correct horse",
    )
    bearer_token = "expired-browser-token"
    now = datetime.now(timezone.utc)
    service.repository.add_session(
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
        service.resolve_session(bearer_token)
