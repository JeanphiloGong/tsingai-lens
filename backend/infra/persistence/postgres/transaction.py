"""Session scopes for standalone and shared PostgreSQL repository calls."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@asynccontextmanager
async def database_session_scope(
    session_factory: async_sessionmaker[AsyncSession],
    transaction: AsyncSession | None,
    *,
    write: bool,
) -> AsyncIterator[AsyncSession]:
    """Use a caller-owned session when present, otherwise open one locally."""

    if transaction is not None:
        yield transaction
        return
    if write:
        async with session_factory.begin() as session:
            yield session
        return
    async with session_factory() as session:
        yield session


__all__ = ["database_session_scope"]
