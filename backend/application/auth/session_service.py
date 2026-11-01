from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from application.auth.passwords import hash_password, verify_password
from exceptions import ProjectException, RequestInvalidException
from repositories.auth_repository import (
    AuthRepo,
    AuthSessionRecord,
    AuthUserRecord,
)

SESSION_COOKIE_NAME = "lens_session"
SESSION_TTL = timedelta(hours=24)


class AuthError(ProjectException):
    """An explicit authentication rejection."""


class InvalidCredentialsError(AuthError):
    def __init__(self, message: str = "Invalid email or password.") -> None:
        super().__init__(
            code=200301, message=message, data={"code": "invalid_credentials"}
        )


class SessionNotFoundError(AuthError):
    def __init__(self, message: str = "Authentication is required.") -> None:
        super().__init__(
            code=200301, message=message, data={"code": "authentication_required"}
        )


async def ensure_bootstrap_user() -> dict[str, Any] | None:
    email = _clean_text(os.getenv("BOOTSTRAP_ADMIN_EMAIL"))
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
    if not email or not password:
        return None
    user = await AuthRepo.read_user_by_email(email)
    if user:
        return _public_user(user)
    return await create_user(
        email=email,
        password=password,
        display_name=os.getenv("BOOTSTRAP_ADMIN_NAME") or "Admin",
    )


async def create_user(
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
    await AuthRepo.add_user(user)
    return _public_user(user)


async def login(*, email: str, password: str) -> dict[str, Any]:
    try:
        login_email = _required_text(email, "email")
    except ValueError as exc:
        raise RequestInvalidException(str(exc)) from exc
    user = await AuthRepo.read_user_by_email(login_email)
    if not user or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("invalid email or password")
    now = datetime.now(timezone.utc)
    bearer_token = secrets.token_urlsafe(32)
    session = AuthSessionRecord(
        session_id=f"session_{uuid4().hex}",
        user_id=user.user_id,
        created_at=now.isoformat(),
        expires_at=(now + SESSION_TTL).isoformat(),
    )
    await AuthRepo.add_session(session, token_hash=_session_token_hash(bearer_token))
    return {
        "session_id": bearer_token,
        "expires_at": session.expires_at,
        "user": _public_user(user),
    }


async def logout(session_id: str | None) -> None:
    if not session_id:
        return
    await AuthRepo.revoke_session_by_token_hash(
        _session_token_hash(session_id),
        _now_iso(),
    )


async def resolve_session(session_id: str | None) -> dict[str, Any]:
    if not session_id:
        raise SessionNotFoundError("authentication required")
    session = await AuthRepo.read_session_by_token_hash(_session_token_hash(session_id))
    if not session or session.revoked_at:
        raise SessionNotFoundError("authentication required")
    if _parse_iso(session.expires_at) <= datetime.now(timezone.utc):
        raise SessionNotFoundError("authentication required")
    user = await AuthRepo.read_user(session.user_id)
    if not user:
        raise SessionNotFoundError("authentication required")
    return _public_user(user)


def _public_user(user: AuthUserRecord) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "email": user.email,
        "display_name": user.display_name,
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


def _required_text(value: str, field_name: str) -> str:
    text = _clean_text(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


__all__ = [
    "AuthError",
    "InvalidCredentialsError",
    "SESSION_COOKIE_NAME",
    "SessionNotFoundError",
]
