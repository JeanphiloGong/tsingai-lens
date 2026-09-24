"""Opaque transaction handles shared by cooperating repositories."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol


class RepositoryTransaction(Protocol):
    """Infrastructure-owned handle for one repository transaction.

    Application contracts intentionally do not depend on SQLAlchemy. Concrete
    persistence adapters may use this handle to reuse their bound session.
    """


class RepositoryTransactionFactory(Protocol):
    """Open a transaction that can be passed to cooperating repositories."""

    def begin(self) -> AbstractAsyncContextManager[RepositoryTransaction]:
        """Return an async context manager yielding a transaction handle."""


__all__ = ["RepositoryTransaction", "RepositoryTransactionFactory"]
