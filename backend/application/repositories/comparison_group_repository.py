"""Repository contract for optional cross-paper comparison groups."""

from __future__ import annotations

from typing import Protocol

from domain.core.comparison_group import ComparisonGroup


class ComparisonGroupRepository(Protocol):
    async def add_group(
        self,
        collection_id: str,
        group: ComparisonGroup,
    ) -> ComparisonGroup: ...

    async def read_group(
        self,
        collection_id: str,
        group_id: str,
    ) -> ComparisonGroup | None: ...

    async def list_groups(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[ComparisonGroup, ...]: ...


__all__ = ["ComparisonGroupRepository"]
