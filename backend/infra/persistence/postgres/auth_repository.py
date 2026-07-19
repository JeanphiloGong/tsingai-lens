"""PostgreSQL persistence for users and browser sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from infra.persistence.postgres.models.auth import AuthSession, AuthUser


class PostgresAuthRepository:
    backend_name = "postgres"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def read_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            user = session.scalar(
                select(AuthUser).where(AuthUser.email == email.strip().lower())
            )
            if user is None:
                return None
            return {
                "user_id": user.user_id,
                "email": user.email,
                "display_name": user.display_name,
                "password_hash": user.password_hash,
                "created_at": _iso(user.created_at),
            }

    def read_user(self, user_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            user = session.get(AuthUser, user_id)
            if user is None:
                return None
            return {
                "user_id": user.user_id,
                "email": user.email,
                "display_name": user.display_name,
                "password_hash": user.password_hash,
                "created_at": _iso(user.created_at),
            }

    def add_user(self, payload: Mapping[str, Any]) -> None:
        with self.session_factory.begin() as session:
            session.add(
                AuthUser(
                    user_id=str(payload["user_id"]),
                    email=str(payload["email"]),
                    display_name=(
                        str(payload["display_name"]).strip() or None
                        if payload.get("display_name") is not None
                        else None
                    ),
                    password_hash=str(payload["password_hash"]),
                    created_at=_datetime(payload["created_at"]),
                )
            )

    def read_session_by_token_hash(
        self,
        token_hash: str,
    ) -> dict[str, Any] | None:
        with self.session_factory() as session:
            auth_session = session.scalar(
                select(AuthSession).where(AuthSession.token_hash == token_hash)
            )
            if auth_session is None:
                return None
            return {
                "session_id": auth_session.session_id,
                "user_id": auth_session.user_id,
                "created_at": _iso(auth_session.created_at),
                "expires_at": _iso(auth_session.expires_at),
                "revoked_at": _optional_iso(auth_session.revoked_at),
            }

    def add_session(self, payload: Mapping[str, Any]) -> None:
        with self.session_factory.begin() as session:
            session.add(
                AuthSession(
                    session_id=str(payload["session_id"]),
                    user_id=str(payload["user_id"]),
                    token_hash=str(payload["token_hash"]),
                    created_at=_datetime(payload["created_at"]),
                    expires_at=_datetime(payload["expires_at"]),
                    revoked_at=_optional_datetime(payload.get("revoked_at")),
                )
            )

    def revoke_session_by_token_hash(self, token_hash: str, revoked_at: str) -> None:
        with self.session_factory.begin() as session:
            session.execute(
                update(AuthSession)
                .where(AuthSession.token_hash == token_hash)
                .values(revoked_at=_datetime(revoked_at))
            )


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        parsed = datetime.fromisoformat(
            f"{text[:-1]}+00:00" if text.endswith("Z") else text
        )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_datetime(value: Any) -> datetime | None:
    return None if value is None else _datetime(value)


def _iso(value: datetime) -> str:
    return _datetime(value).isoformat()


def _optional_iso(value: datetime | None) -> str | None:
    return _iso(value) if value is not None else None


__all__ = ["PostgresAuthRepository"]
