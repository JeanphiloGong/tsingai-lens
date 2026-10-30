from __future__ import annotations

from typing import Annotated

from application.auth import session_service
from application.auth.session_service import SESSION_COOKIE_NAME
from config import COOKIE_SECURE
from controllers.dependencies.auth import get_current_user_id
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from utils.response import ApiResponse, make_api_response


class AuthLoginRequest(BaseModel):
    """Browser login payload."""

    model_config = ConfigDict(extra="ignore")

    email: str = Field(..., description="User email")
    password: str = Field(..., description="User password")


class AuthUserResponse(BaseModel):
    """Authenticated user visible to the browser."""

    user_id: str = Field(..., description="User ID")
    email: str = Field(..., description="Email")
    display_name: str | None = Field(default=None, description="Display name")


class AuthSessionResponse(BaseModel):
    """Current browser session state."""

    user: AuthUserResponse


class AuthLogoutResponse(BaseModel):
    """Logout result."""

    ok: bool = True


auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post(
    "/login", response_model=ApiResponse[AuthSessionResponse], summary="Log in"
)
async def login(
    payload: AuthLoginRequest,
) -> Response:
    session = await session_service.login(
        email=payload.email,
        password=payload.password,
    )

    response = make_api_response(data=AuthSessionResponse(user=session["user"]))
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session["session_id"],
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return response


@auth_router.post(
    "/logout", response_model=ApiResponse[AuthLogoutResponse], summary="Log out"
)
async def logout(request: Request) -> Response:
    await session_service.logout(request.cookies.get(SESSION_COOKIE_NAME))
    response = make_api_response(data=AuthLogoutResponse(ok=True))
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax")
    return response


@auth_router.get(
    "/me", response_model=ApiResponse[AuthSessionResponse], summary="Read current user"
)
async def me(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> Response:
    return make_api_response(data=AuthSessionResponse(user=request.state.current_user))
