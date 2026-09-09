"""PostgreSQL persistence for users and browser sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from application.repositories.auth_repository import AuthSessionRecord, AuthUserRecord

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infra.persistence.postgres.models.auth import AuthSession, AuthUser


class PostgresAuthRepository:
    backend_name = "postgres"

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.session_factory = session_factory

    async def read_user_by_email(self, email: str) -> AuthUserRecord | None:
        async with self.session_factory() as session:
            user = await session.scalar(
                select(AuthUser).where(AuthUser.email == email.strip().lower())
            )
            return _user_record(user) if user is not None else None

    async def read_user(self, user_id: str) -> AuthUserRecord | None:
        async with self.session_factory() as session:
            user = await session.get(AuthUser, user_id)
            return _user_record(user) if user is not None else None

    async def add_user(self, user: AuthUserRecord) -> None:
        async with self.session_factory.begin() as session:
            session.add(
                AuthUser(
                    user_id=user.user_id,
                    email=user.email,
                    display_name=(
                        user.display_name.strip() or None
                        if user.display_name is not None
                        else None
                    ),
                    password_hash=user.password_hash,
                    created_at=_datetime(user.created_at),
                )
            )

    async def read_session_by_token_hash(
        self,
        token_hash: str,
    ) -> AuthSessionRecord | None:
        async with self.session_factory() as session:
            auth_session = await session.scalar(
                select(AuthSession).where(AuthSession.token_hash == token_hash)
            )
            if auth_session is None:
                return None
            return AuthSessionRecord(
                session_id=auth_session.session_id,
                user_id=auth_session.user_id,
                created_at=_iso(auth_session.created_at),
                expires_at=_iso(auth_session.expires_at),
                revoked_at=_optional_iso(auth_session.revoked_at),
            )

    async def add_session(self, session: AuthSessionRecord, *, token_hash: str) -> None:
        async with self.session_factory.begin() as database_session:
            database_session.add(
                AuthSession(
                    session_id=session.session_id,
                    user_id=session.user_id,
                    token_hash=token_hash,
                    created_at=_datetime(session.created_at),
                    expires_at=_datetime(session.expires_at),
                    revoked_at=_optional_datetime(session.revoked_at),
                )
            )

    async def revoke_session_by_token_hash(
        self, token_hash: str, revoked_at: str
    ) -> None:
        async with self.session_factory.begin() as session:
            await session.execute(
                update(AuthSession)
                .where(AuthSession.token_hash == token_hash)
                .values(revoked_at=_datetime(revoked_at))
            )


def _user_record(user: AuthUser) -> AuthUserRecord:
    return AuthUserRecord(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        password_hash=user.password_hash,
        created_at=_iso(user.created_at),
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
