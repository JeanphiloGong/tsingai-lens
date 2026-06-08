from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import uuid4

from application.auth.passwords import hash_password, verify_password
from infra.persistence.factory import build_auth_repository

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
        repository: Any | None = None,
        *,
        session_ttl_hours: int = DEFAULT_SESSION_TTL_HOURS,
    ) -> None:
        self.repository = repository or build_auth_repository()
        self.session_ttl = timedelta(hours=session_ttl_hours)

    def ensure_bootstrap_user(self) -> dict[str, Any] | None:
        email = _clean_text(os.getenv("BOOTSTRAP_ADMIN_EMAIL"))
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
        if not email or not password:
            return None
        user = self.repository.read_user_by_email(email)
        if user:
            return _public_user(user)
        return self.create_user(
            email=email,
            password=password,
            display_name=os.getenv("BOOTSTRAP_ADMIN_NAME") or "Admin",
        )

    def create_user(
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
        user = {
            "user_id": f"user_{uuid4().hex[:12]}",
            "email": normalized_email,
            "display_name": _clean_text(display_name),
            "password_hash": hash_password(password),
            "created_at": now,
        }
        self.repository.write_user(user)
        return _public_user(user)

    def login(self, *, email: str, password: str) -> dict[str, Any]:
        user = self.repository.read_user_by_email(_required_text(email, "email"))
        if not user or not verify_password(password, str(user["password_hash"])):
            raise InvalidCredentialsError("invalid email or password")
        now = datetime.now(timezone.utc)
        session = {
            "session_id": secrets.token_urlsafe(32),
            "user_id": str(user["user_id"]),
            "created_at": now.isoformat(),
            "expires_at": (now + self.session_ttl).isoformat(),
            "revoked_at": None,
        }
        self.repository.write_session(session)
        return {
            "session_id": session["session_id"],
            "expires_at": session["expires_at"],
            "user": _public_user(user),
        }

    def logout(self, session_id: str | None) -> None:
        if not session_id:
            return
        self.repository.revoke_session(session_id, _now_iso())

    def resolve_session(self, session_id: str | None) -> dict[str, Any]:
        if not session_id:
            raise SessionNotFoundError("authentication required")
        session = self.repository.read_session(session_id)
        if not session or session.get("revoked_at"):
            raise SessionNotFoundError("authentication required")
        if _parse_iso(str(session["expires_at"])) <= datetime.now(timezone.utc):
            raise SessionNotFoundError("authentication required")
        user = self.repository.read_user(str(session["user_id"]))
        if not user:
            raise SessionNotFoundError("authentication required")
        return _public_user(user)


def _public_user(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(payload["user_id"]),
        "email": str(payload["email"]),
        "display_name": _clean_text(payload.get("display_name")),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
