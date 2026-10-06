"""Persistence contract for immutable feedback dataset snapshots."""

from __future__ import annotations

from typing import Protocol

from domain.feedback.dataset_snapshot import DatasetSnapshot, DatasetType


class DatasetSnapshotRepository(Protocol):
    async def save(self, snapshot: DatasetSnapshot) -> DatasetSnapshot: ...

    async def read(self, dataset_id: str) -> DatasetSnapshot | None: ...

    async def list_for_owner(
        self,
        *,
        owner_id: str,
        collection_id: str | None = None,
        dataset_type: DatasetType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[DatasetSnapshot, ...]: ...


__all__ = ["DatasetSnapshotRepository"]
