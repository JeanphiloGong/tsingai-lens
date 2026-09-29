"""Persistence contract for maintained feedback datasets."""

from __future__ import annotations

from typing import Protocol

from domain.feedback.dataset import Dataset


class FeedbackDatasetRepository(Protocol):
    async def create(self, dataset: Dataset) -> Dataset: ...

    async def read(self, dataset_id: str) -> Dataset | None: ...

    async def list_for_collection(
        self,
        *,
        collection_id: str,
        limit: int,
        offset: int,
    ) -> tuple[Dataset, ...]: ...


__all__ = ["FeedbackDatasetRepository"]
