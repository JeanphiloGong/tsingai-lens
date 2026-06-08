from __future__ import annotations

import pytest

from application.auth import (
    AuthSessionService,
    InvalidCredentialsError,
    SessionNotFoundError,
)
from infra.persistence.sqlite.auth_repository import SqliteAuthRepository


def test_auth_session_service_logs_in_and_resolves_user(tmp_path):
    service = AuthSessionService(
        SqliteAuthRepository(tmp_path / "lens.sqlite"),
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


def test_auth_session_service_rejects_bad_password(tmp_path):
    service = AuthSessionService(SqliteAuthRepository(tmp_path / "lens.sqlite"))
    service.create_user(email="reader@example.com", password="correct horse")

    with pytest.raises(InvalidCredentialsError):
        service.login(email="reader@example.com", password="wrong")


def test_auth_session_service_logout_revokes_session(tmp_path):
    service = AuthSessionService(SqliteAuthRepository(tmp_path / "lens.sqlite"))
    service.create_user(email="reader@example.com", password="correct horse")
    session = service.login(email="reader@example.com", password="correct horse")

    service.logout(session["session_id"])

    with pytest.raises(SessionNotFoundError):
        service.resolve_session(session["session_id"])
