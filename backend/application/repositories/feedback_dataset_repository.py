"""Persistence contract for maintained feedback datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from domain.feedback.dataset import Dataset


@dataclass(frozen=True)
class StoredDataset:
    dataset: Dataset
    created_at: datetime
    updated_at: datetime


class FeedbackDatasetRepository(Protocol):
    async def create(self, dataset: Dataset) -> Dataset: ...

    async def ensure_system_datasets(
        self,
        *,
        collection_id: str,
        owner_user_id: str,
    ) -> tuple[Dataset, ...]: ...

    async def read(self, dataset_id: str) -> Dataset | None: ...

    async def read_record(self, dataset_id: str) -> StoredDataset | None: ...

    async def list_records_for_collection(
        self,
        *,
        collection_id: str,
        limit: int,
        offset: int,
    ) -> tuple[StoredDataset, ...]: ...


__all__ = ["FeedbackDatasetRepository", "StoredDataset"]
