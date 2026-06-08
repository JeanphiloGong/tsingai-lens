from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from application.auth.session_service import SESSION_COOKIE_NAME, SessionNotFoundError


def auth_required_detail() -> dict[str, str]:
    return {
        "code": "authentication_required",
        "message": "Authentication is required.",
    }


def require_current_user(request: Request) -> dict[str, Any]:
    current_user = getattr(request.state, "current_user", None)
    if current_user:
        return dict(current_user)
    try:
        return request.app.state.auth_session_service.resolve_session(
            request.cookies.get(SESSION_COOKIE_NAME)
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=401, detail=auth_required_detail()) from exc


def current_user_id(request: Request) -> str:
    return str(require_current_user(request)["user_id"])


__all__ = ["auth_required_detail", "current_user_id", "require_current_user"]
