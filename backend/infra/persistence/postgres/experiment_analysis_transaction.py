"""Shared transaction factory for automatic experiment publication."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.repositories.transaction import (
    RepositoryTransaction,
    RepositoryTransactionFactory,
)


class PostgresExperimentAnalysisTransactionFactory(RepositoryTransactionFactory):
    """Yield one AsyncSession for the complete analysis publication event."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[RepositoryTransaction]:
        async with self.session_factory.begin() as session:
            yield session


__all__ = ["PostgresExperimentAnalysisTransactionFactory"]
