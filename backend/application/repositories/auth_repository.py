from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class AuthUserRecord:
    user_id: str
    email: str
    display_name: str | None
    password_hash: str = field(repr=False)
    created_at: str


@dataclass(frozen=True)
class AuthSessionRecord:
    session_id: str
    user_id: str
    created_at: str
    expires_at: str
    revoked_at: str | None = None


class AuthRepository(Protocol):
    async def read_user_by_email(self, email: str) -> AuthUserRecord | None: ...

    async def read_user(self, user_id: str) -> AuthUserRecord | None: ...

    async def add_user(self, user: AuthUserRecord) -> None: ...

    async def read_session_by_token_hash(self, token_hash: str) -> AuthSessionRecord | None: ...

    async def add_session(self, session: AuthSessionRecord, *, token_hash: str) -> None: ...

    async def revoke_session_by_token_hash(self, token_hash: str, revoked_at: str) -> None: ...
