"""Repository contract for optional cross-paper comparison groups."""

from __future__ import annotations

from typing import Protocol

from application.repositories.transaction import RepositoryTransaction
from domain.core.comparison_group import ComparisonGroup


class ComparisonGroupRepository(Protocol):
    async def add_group(
        self,
        collection_id: str,
        group: ComparisonGroup,
        *,
        transaction: RepositoryTransaction | None = None,
    ) -> ComparisonGroup: ...

    async def read_group(
        self,
        collection_id: str,
        group_id: str,
        *,
        transaction: RepositoryTransaction | None = None,
    ) -> ComparisonGroup | None: ...

    async def list_groups(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        transaction: RepositoryTransaction | None = None,
    ) -> tuple[ComparisonGroup, ...]: ...


__all__ = ["ComparisonGroupRepository"]
