from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from application.auth.passwords import hash_password, verify_password
from application.repositories.auth_repository import (
    AuthRepository,
    AuthSessionRecord,
    AuthUserRecord,
)

SESSION_COOKIE_NAME = "lens_session"
DEFAULT_SESSION_TTL_HOURS = 24


class AuthError(RuntimeError):
    """Base class for authentication failures."""


class InvalidCredentialsError(AuthError):
    """Raised when login credentials do not match a user."""


class SessionNotFoundError(AuthError):
    """Raised when a browser session is missing or no longer valid."""


class AuthSessionService:
    """Owns private-beta password auth and server-side sessions."""

    def __init__(
        self,
        repository: AuthRepository,
        *,
        session_ttl_hours: int = DEFAULT_SESSION_TTL_HOURS,
    ) -> None:
        self.repository = repository
        self.session_ttl = timedelta(hours=session_ttl_hours)

    async def ensure_bootstrap_user(self) -> dict[str, Any] | None:
        email = _clean_text(os.getenv("BOOTSTRAP_ADMIN_EMAIL"))
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
        if not email or not password:
            return None
        user = await self.repository.read_user_by_email(email)
        if user:
            return _public_user(user)
        return await self.create_user(
            email=email,
            password=password,
            display_name=os.getenv("BOOTSTRAP_ADMIN_NAME") or "Admin",
        )

    async def create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_email = _required_text(email, "email").lower()
        if not password:
            raise ValueError("password is required")
        now = _now_iso()
        user = AuthUserRecord(
            user_id=f"user_{uuid4().hex[:12]}",
            email=normalized_email,
            display_name=_clean_text(display_name),
            password_hash=hash_password(password),
            created_at=now,
        )
        await self.repository.add_user(user)
        return _public_user(user)

    async def login(self, *, email: str, password: str) -> dict[str, Any]:
        user = await self.repository.read_user_by_email(
            _required_text(email, "email")
        )
        if not user or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("invalid email or password")
        now = datetime.now(timezone.utc)
        bearer_token = secrets.token_urlsafe(32)
        session = AuthSessionRecord(
            session_id=f"session_{uuid4().hex}",
            user_id=user.user_id,
            created_at=now.isoformat(),
            expires_at=(now + self.session_ttl).isoformat(),
        )
        await self.repository.add_session(session, token_hash=_session_token_hash(bearer_token))
        return {
            "session_id": bearer_token,
            "expires_at": session.expires_at,
            "user": _public_user(user),
        }

    async def logout(self, session_id: str | None) -> None:
        if not session_id:
            return
        await self.repository.revoke_session_by_token_hash(
            _session_token_hash(session_id),
            _now_iso(),
        )

    async def resolve_session(
        self, session_id: str | None
    ) -> dict[str, Any]:
        if not session_id:
            raise SessionNotFoundError("authentication required")
        session = await self.repository.read_session_by_token_hash(
            _session_token_hash(session_id)
        )
        if not session or session.revoked_at:
            raise SessionNotFoundError("authentication required")
        if _parse_iso(session.expires_at) <= datetime.now(timezone.utc):
            raise SessionNotFoundError("authentication required")
        user = await self.repository.read_user(session.user_id)
        if not user:
            raise SessionNotFoundError("authentication required")
        return _public_user(user)


def _public_user(user: AuthUserRecord) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "email": user.email,
        "display_name": _clean_text(user.display_name),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _session_token_hash(session_token: str) -> str:
    return sha256(session_token.encode("utf-8")).hexdigest()


def _required_text(value: Any, field_name: str) -> str:
    text = _clean_text(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "AuthError",
    "AuthSessionService",
    "InvalidCredentialsError",
    "SESSION_COOKIE_NAME",
    "SessionNotFoundError",
]
