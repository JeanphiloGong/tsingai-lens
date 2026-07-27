from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from infra.persistence.database import build_session_factory
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from tests.integration.persistence.database_cleanup import reset_postgres_schema
from infra.persistence.postgres.models.auth import AuthSession


BACKEND_ROOT = Path(__file__).resolve().parents[3]


def test_auth_repository_round_trips_users_and_sessions(
    auth_session_service,
) -> None:
    repository = auth_session_service.repository
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    token_hash = sha256(b"browser-session-token").hexdigest()
    user = {
        "user_id": "user_reader",
        "email": "reader@example.com",
        "display_name": "Reader",
        "password_hash": "synthetic-password-hash",
        "created_at": now.isoformat(),
    }
    session = {
        "session_id": "session_reader",
        "user_id": user["user_id"],
        "token_hash": token_hash,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "revoked_at": None,
    }

    repository.add_user(user)
    repository.add_session(session)

    assert repository.read_user(user["user_id"]) == user
    assert repository.read_user_by_email("READER@EXAMPLE.COM") == user
    assert repository.read_session_by_token_hash(token_hash) == {
        key: value for key, value in session.items() if key != "token_hash"
    }

    revoked_at = (now + timedelta(minutes=5)).isoformat()
    repository.revoke_session_by_token_hash(token_hash, revoked_at)

    assert repository.read_session_by_token_hash(token_hash)["revoked_at"] == revoked_at


def test_auth_repository_rejects_duplicate_email_and_token_hash(
    auth_session_service,
) -> None:
    repository = auth_session_service.repository
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    first_user = {
        "user_id": "user_first",
        "email": "reader@example.com",
        "display_name": None,
        "password_hash": "synthetic-password-hash",
        "created_at": now.isoformat(),
    }
    repository.add_user(first_user)

    with pytest.raises(IntegrityError):
        repository.add_user({**first_user, "user_id": "user_second"})

    token_hash = sha256(b"one-browser-token").hexdigest()
    first_session = {
        "session_id": "session_first",
        "user_id": first_user["user_id"],
        "token_hash": token_hash,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "revoked_at": None,
    }
    repository.add_session(first_session)

    with pytest.raises(IntegrityError):
        repository.add_session({**first_session, "session_id": "session_second"})


def test_postgresql_enforces_auth_contract(monkeypatch) -> None:
    database_url = os.getenv("LENS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("LENS_TEST_DATABASE_URL is not configured")
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg" or not str(url.database).endswith(
        "_test"
    ):
        pytest.fail(
            "LENS_TEST_DATABASE_URL must use postgresql+psycopg and a *_test database"
        )

    engine = create_engine(url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    reset_postgres_schema(engine)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    repository = PostgresAuthRepository(build_session_factory(engine))
    try:
        now = datetime(2026, 7, 19, tzinfo=timezone.utc)
        user = {
            "user_id": "user_constraints",
            "email": "constraints@example.com",
            "display_name": None,
            "password_hash": "synthetic-password-hash",
            "created_at": now.isoformat(),
        }
        repository.add_user(user)

        with pytest.raises(IntegrityError):
            repository.add_user(
                {
                    **user,
                    "user_id": "user_uppercase",
                    "email": "UPPERCASE@example.com",
                }
            )

        token_hash = sha256(b"constraint-token").hexdigest()
        session = {
            "session_id": "session_constraints",
            "user_id": user["user_id"],
            "token_hash": token_hash,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "revoked_at": None,
        }
        repository.add_session(session)

        with pytest.raises(IntegrityError):
            repository.add_session(
                {
                    **session,
                    "session_id": "session_duplicate_token",
                }
            )
        with pytest.raises(IntegrityError):
            repository.add_session(
                {
                    **session,
                    "session_id": "session_orphan",
                    "user_id": "user_missing",
                    "token_hash": sha256(b"orphan-token").hexdigest(),
                }
            )
        with pytest.raises(IntegrityError):
            repository.add_session(
                {
                    **session,
                    "session_id": "session_invalid_expiry",
                    "token_hash": sha256(b"invalid-expiry-token").hexdigest(),
                    "expires_at": now.isoformat(),
                }
            )

        monkeypatch.setenv("LENS_DATABASE_URL", database_url)
        monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin-password")
        monkeypatch.setenv("COOKIE_SECURE", "false")

        from main import create_app

        monkeypatch.setattr(
            "main.FindingSynthesisService",
            lambda **_kwargs: object(),
        )
        monkeypatch.setattr("main.GoalSessionService", lambda **_kwargs: object())
        with TestClient(create_app()) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "admin-password"},
            )
            assert login.status_code == 200
            bearer_token = client.cookies.get("lens_session")
            assert bearer_token

            with repository.session_factory() as database_session:
                stored = database_session.scalar(
                    select(AuthSession).where(
                        AuthSession.token_hash
                        == sha256(bearer_token.encode("utf-8")).hexdigest()
                    )
                )
            assert stored is not None
            assert stored.session_id != bearer_token

            me = client.get("/api/v1/auth/me")
            assert me.status_code == 200
            assert me.json()["user"]["email"] == "admin@example.com"

            logout = client.post("/api/v1/auth/logout")
            assert logout.status_code == 200
            assert client.get("/api/v1/auth/me").status_code == 401
    finally:
        reset_postgres_schema(engine)
        engine.dispose()
