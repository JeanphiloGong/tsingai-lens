from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request, Response

from application.auth.session_service import (
    SESSION_COOKIE_NAME,
    InvalidCredentialsError,
)
from controllers.dependencies.auth import require_current_user
from controllers.schemas.auth import (
    AuthLoginRequest,
    AuthLogoutResponse,
    AuthSessionResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthSessionResponse, summary="Log in")
async def login(
    payload: AuthLoginRequest,
    request: Request,
    response: Response,
) -> AuthSessionResponse:
    try:
        session = request.app.state.auth_session_service.login(
            email=payload.email,
            password=payload.password,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "invalid_credentials",
                "message": "Invalid email or password.",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response.set_cookie(
        SESSION_COOKIE_NAME,
        session["session_id"],
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )
    return AuthSessionResponse(user=session["user"])


@router.post("/logout", response_model=AuthLogoutResponse, summary="Log out")
async def logout(request: Request, response: Response) -> AuthLogoutResponse:
    request.app.state.auth_session_service.logout(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax")
    return AuthLogoutResponse(ok=True)


@router.get("/me", response_model=AuthSessionResponse, summary="Read current user")
async def me(request: Request) -> AuthSessionResponse:
    return AuthSessionResponse(user=require_current_user(request))


def _cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes"}
