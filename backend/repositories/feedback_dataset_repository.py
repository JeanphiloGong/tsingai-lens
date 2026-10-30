"""PostgreSQL repository for feedback dataset."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infra.persistence.database import AsyncSessionLocal

from domain.feedback.dataset import Dataset, DatasetTaskType
from infra.persistence.postgres.models.feedback_dataset import FeedbackDatasetRow


@dataclass(frozen=True)
class StoredDataset:
    dataset: Dataset
    created_at: datetime
    updated_at: datetime


_SYSTEM_TASKS: tuple[tuple[DatasetTaskType, str], ...] = (
    ("sft", "文献问答 SFT"),
    ("preference", "回答偏好"),
    ("evaluation", "评测"),
)


def system_dataset_id(collection_id: str, task_type: str) -> str:
    digest = sha256(f"{collection_id}\x1f{task_type}".encode("utf-8")).hexdigest()[:32]
    return f"fdset_system_{digest}"


class FeedbackDatasetRepository:
    backend_name = "postgresql"

    async def create(self, dataset: Dataset) -> Dataset:
        async with AsyncSessionLocal() as db, db.begin():
            now = datetime.now(timezone.utc)
            row = FeedbackDatasetRow(
                dataset_id=dataset.dataset_id,
                collection_id=dataset.collection_id,
                name=dataset.name,
                task_type=dataset.task_type,
                construction_spec=dataset.construction_spec,
                spec_version=dataset.spec_version,
                created_by=dataset.created_by,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.flush()
        return dataset

    async def read(self, dataset_id: str) -> Dataset | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(FeedbackDatasetRow, dataset_id)
            if row is None:
                return None
            return Dataset(
                dataset_id=row.dataset_id,
                collection_id=row.collection_id,
                name=row.name,
                task_type=row.task_type,
                construction_spec=row.construction_spec,
                spec_version=row.spec_version,
                created_by=row.created_by,
            )

    async def read_record(self, dataset_id: str) -> StoredDataset | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(FeedbackDatasetRow, dataset_id)
            if row is None:
                return None
            return StoredDataset(
                dataset=Dataset(
                    dataset_id=row.dataset_id,
                    collection_id=row.collection_id,
                    name=row.name,
                    task_type=row.task_type,
                    construction_spec=row.construction_spec,
                    spec_version=row.spec_version,
                    created_by=row.created_by,
                ),
                created_at=_datetime(row.created_at),
                updated_at=_datetime(row.updated_at),
            )

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
        async with AsyncSessionLocal() as db:
            return tuple(
                StoredDataset(
                    dataset=Dataset(
                        dataset_id=row.dataset_id,
                        collection_id=row.collection_id,
                        name=row.name,
                        task_type=row.task_type,
                        construction_spec=row.construction_spec,
                        spec_version=row.spec_version,
                        created_by=row.created_by,
                    ),
                    created_at=_datetime(row.created_at),
                    updated_at=_datetime(row.updated_at),
                )
                for row in await db.scalars(statement)
            )


async def ensure_system_datasets(
    db: AsyncSession, *, collection_id: str, owner_user_id: str, now: datetime,
) -> tuple[Dataset, ...]:
    """Use the caller's transaction for collection creation and case writes."""
    records: list[Dataset] = []
    for task_type, name in _SYSTEM_TASKS:
        dataset_id = system_dataset_id(collection_id, task_type)
        row = await db.get(FeedbackDatasetRow, dataset_id)
        if row is None:
            dataset = Dataset(
                dataset_id=dataset_id,
                collection_id=collection_id,
                name=name,
                task_type=task_type,
                construction_spec={"mode": "automatic_feedback_workbench", "source": "feedback_case"},
                spec_version=1,
                created_by=owner_user_id,
            )
            try:
                async with db.begin_nested():
                    db.add(FeedbackDatasetRow(
                        dataset_id=dataset.dataset_id,
                        collection_id=dataset.collection_id,
                        name=dataset.name,
                        task_type=dataset.task_type,
                        construction_spec=dataset.construction_spec,
                        spec_version=dataset.spec_version,
                        created_by=dataset.created_by,
                        created_at=now,
                        updated_at=now,
                    ))
                    await db.flush()
            except IntegrityError:
                row = await db.get(FeedbackDatasetRow, dataset_id)
            else:
                records.append(dataset)
                continue
        if row is None:
            raise RuntimeError("system feedback dataset creation raced and was not readable")
        records.append(Dataset(
            dataset_id=row.dataset_id,
            collection_id=row.collection_id,
            name=row.name,
            task_type=row.task_type,
            construction_spec=row.construction_spec,
            spec_version=row.spec_version,
            created_by=row.created_by,
        ))
    return tuple(records)


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


__all__ = ['FeedbackDatasetRepository', 'StoredDataset']


FeedbackDatasetRepo = FeedbackDatasetRepository()
