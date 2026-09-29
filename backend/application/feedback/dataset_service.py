"""Application operations for maintained feedback datasets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from application.repositories.feedback_dataset_repository import (
    FeedbackDatasetRepository,
)
from application.source.collection_service import CollectionService
from domain.feedback.dataset import Dataset


class FeedbackDatasetError(ValueError):
    """A user-correctable dataset request."""


_FORBIDDEN_SPEC_KEYS = frozenset({"api_key", "token", "password", "secret", "credential"})


class FeedbackDatasetService:
    def __init__(
        self,
        *,
        repository: FeedbackDatasetRepository,
        collection_service: CollectionService,
    ) -> None:
        self.repository = repository
        self.collection_service = collection_service

    async def create_for_user(
        self,
        *,
        user_id: str,
        collection_id: str,
        name: str,
        task_type: str,
        construction_spec: dict[str, Any],
    ) -> Dataset:
        await self.collection_service.get_collection_for_user(collection_id, user_id)
        if task_type != "sft":
            raise FeedbackDatasetError("dataset_task_type_not_available")
        cleaned_name = name.strip()
        if not cleaned_name:
            raise FeedbackDatasetError("dataset_name_required")
        _validate_public_spec(construction_spec)
        now = datetime.now(timezone.utc)
        dataset = Dataset(
            dataset_id=f"fdset_{uuid4().hex[:32]}",
            collection_id=collection_id,
            name=cleaned_name,
            task_type="sft",
            construction_spec=construction_spec,
            spec_version=1,
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
        return await self.repository.create(dataset)

    async def list_for_user(
        self,
        *,
        user_id: str,
        collection_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Dataset, ...]:
        await self.collection_service.get_collection_for_user(collection_id, user_id)
        if limit < 1 or limit > 200 or offset < 0:
            raise FeedbackDatasetError("pagination_invalid")
        return await self.repository.list_for_collection(
            collection_id=collection_id,
            limit=limit,
            offset=offset,
        )

    async def read_for_user(self, *, user_id: str, dataset_id: str) -> Dataset:
        dataset = await self.repository.read(dataset_id)
        if dataset is None:
            raise FileNotFoundError(f"dataset not found: {dataset_id}")
        await self.collection_service.get_collection_for_user(
            dataset.collection_id,
            user_id,
        )
        return dataset


def _validate_public_spec(value: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise FeedbackDatasetError("construction_spec_invalid")

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).lower() in _FORBIDDEN_SPEC_KEYS:
                    raise FeedbackDatasetError("construction_spec_contains_credential")
                walk(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child)

    walk(value)


__all__ = ["FeedbackDatasetError", "FeedbackDatasetService"]
