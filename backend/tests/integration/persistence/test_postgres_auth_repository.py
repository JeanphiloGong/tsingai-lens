from __future__ import annotations

from dataclasses import replace
from application.repositories.auth_repository import AuthSessionRecord, AuthUserRecord

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.models.auth import AuthSession


pytestmark = pytest.mark.anyio


async def test_auth_repository_round_trips_users_and_sessions(
    postgres_session_factory,
) -> None:
    repository = PostgresAuthRepository(postgres_session_factory)
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    token_hash = sha256(b"browser-session-token").hexdigest()
    user = AuthUserRecord(
        user_id="user_reader", email="reader@example.com", display_name="Reader",
        password_hash="synthetic-password-hash", created_at=now.isoformat(),
    )
    session = AuthSessionRecord(
        session_id="session_reader", user_id=user.user_id,
        created_at=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat(),
    )

    await repository.add_user(user)
    await repository.add_session(session=session, token_hash=token_hash)

    assert await repository.read_user(user.user_id) == user
    assert await repository.read_user_by_email("READER@EXAMPLE.COM") == user
    assert await repository.read_session_by_token_hash(token_hash) == session

    revoked_at = (now + timedelta(minutes=5)).isoformat()
    await repository.revoke_session_by_token_hash(token_hash, revoked_at)

    stored = await repository.read_session_by_token_hash(token_hash)
    assert stored is not None
    assert stored.revoked_at == revoked_at


async def test_auth_repository_rejects_duplicate_email_and_token_hash(
    postgres_session_factory,
) -> None:
    repository = PostgresAuthRepository(postgres_session_factory)
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    first_user = AuthUserRecord(
        user_id="user_first", email="reader@example.com", display_name=None,
        password_hash="synthetic-password-hash", created_at=now.isoformat(),
    )
    await repository.add_user(first_user)

    with pytest.raises(IntegrityError):
        await repository.add_user(replace(first_user, user_id="user_second"))

    token_hash = sha256(b"one-browser-token").hexdigest()
    first_session = AuthSessionRecord(
        session_id="session_first", user_id=first_user.user_id,
        created_at=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat(),
    )
    await repository.add_session(first_session, token_hash=token_hash)

    with pytest.raises(IntegrityError):
        await repository.add_session(
            replace(first_session, session_id="session_second"), token_hash=token_hash,
        )


async def test_postgresql_enforces_auth_contract(
    monkeypatch,
    postgres_session_factory,
) -> None:
    repository = PostgresAuthRepository(postgres_session_factory)
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    user = AuthUserRecord(
        user_id="user_constraints", email="constraints@example.com", display_name=None,
        password_hash="synthetic-password-hash", created_at=now.isoformat(),
    )
    await repository.add_user(user)

    with pytest.raises(IntegrityError):
        await repository.add_user(
            replace(user, user_id="user_uppercase", email="UPPERCASE@example.com")
        )

    token_hash = sha256(b"constraint-token").hexdigest()
    session = AuthSessionRecord(
        session_id="session_constraints", user_id=user.user_id,
        created_at=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat(),
    )
    await repository.add_session(session, token_hash=token_hash)

    with pytest.raises(IntegrityError):
        await repository.add_session(
            replace(session, session_id="session_duplicate_token"), token_hash=token_hash,
        )
    with pytest.raises(IntegrityError):
        await repository.add_session(
            replace(session, session_id="session_orphan", user_id="user_missing"),
            token_hash=sha256(b"orphan-token").hexdigest(),
        )
    with pytest.raises(IntegrityError):
        await repository.add_session(
            replace(session, session_id="session_invalid_expiry", expires_at=now.isoformat()),
            token_hash=sha256(b"invalid-expiry-token").hexdigest(),
        )

    database_url = os.environ["LENS_TEST_DATABASE_URL"]
    monkeypatch.setenv("LENS_DATABASE_URL", database_url)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    from main import create_app

    monkeypatch.setattr(
        "main.FindingSynthesisService",
        lambda **_kwargs: object(),
    )
    with TestClient(create_app()) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin-password"},
        )
        assert login.status_code == 200
        bearer_token = client.cookies.get("lens_session")
        assert bearer_token

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["email"] == "admin@example.com"

        logout = client.post("/api/v1/auth/logout")
        assert logout.status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 401

    async with repository.session_factory() as database_session:
        stored = await database_session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash
                == sha256(bearer_token.encode("utf-8")).hexdigest()
            )
        )
    assert stored is not None
    assert stored.session_id != bearer_token
