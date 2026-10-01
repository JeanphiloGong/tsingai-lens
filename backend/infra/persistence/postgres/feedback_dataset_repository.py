"""PostgreSQL persistence for maintained feedback datasets."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.repositories.feedback_dataset_repository import StoredDataset
from domain.feedback.dataset import Dataset
from infra.persistence.postgres.models.feedback_dataset import FeedbackDatasetRow


class PostgresFeedbackDatasetRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def create(self, dataset: Dataset) -> Dataset:
        async with self.session_factory.begin() as session:
            row = FeedbackDatasetRow(**_row_values(dataset))
            session.add(row)
            await session.flush()
        return dataset

    async def read(self, dataset_id: str) -> Dataset | None:
        async with self.session_factory() as session:
            row = await session.get(FeedbackDatasetRow, dataset_id)
            return _to_domain(row) if row is not None else None

    async def read_record(self, dataset_id: str) -> StoredDataset | None:
        async with self.session_factory() as session:
            row = await session.get(FeedbackDatasetRow, dataset_id)
            return _to_record(row) if row is not None else None

    async def list_records_for_collection(
        self,
        *,
        collection_id: str,
        limit: int,
        offset: int,
    ) -> tuple[StoredDataset, ...]:
        statement = (
            select(FeedbackDatasetRow)
            .where(FeedbackDatasetRow.collection_id == collection_id)
            .order_by(
                FeedbackDatasetRow.created_at.desc(), FeedbackDatasetRow.dataset_id
            )
            .offset(offset)
            .limit(limit)
        )
        async with self.session_factory() as session:
            return tuple(_to_record(row) for row in await session.scalars(statement))


def _row_values(dataset: Dataset) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "dataset_id": dataset.dataset_id,
        "collection_id": dataset.collection_id,
        "name": dataset.name,
        "task_type": dataset.task_type,
        "construction_spec": deepcopy(dataset.construction_spec),
        "spec_version": dataset.spec_version,
        "created_by": dataset.created_by,
        "created_at": now,
        "updated_at": now,
    }


def _to_domain(row: FeedbackDatasetRow) -> Dataset:
    return Dataset(
        dataset_id=row.dataset_id,
        collection_id=row.collection_id,
        name=row.name,
        task_type=row.task_type,  # type: ignore[arg-type]
        construction_spec=deepcopy(row.construction_spec or {}),
        spec_version=row.spec_version,
        created_by=row.created_by,
    )


def _to_record(row: FeedbackDatasetRow) -> StoredDataset:
    return StoredDataset(
        dataset=_to_domain(row),
        created_at=_datetime(row.created_at),
        updated_at=_datetime(row.updated_at),
    )


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        parsed = datetime.fromisoformat(
            f"{text[:-1]}+00:00" if text.endswith("Z") else text
        )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = ["PostgresFeedbackDatasetRepository"]
