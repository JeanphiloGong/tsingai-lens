from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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
