"""PostgreSQL persistence for frozen feedback dataset snapshots."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.feedback import DatasetSnapshot
from infra.persistence.postgres.models.feedback import FeedbackDatasetSnapshotRow


class PostgresDatasetSnapshotRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save(self, snapshot: DatasetSnapshot) -> DatasetSnapshot:
        async with self.session_factory.begin() as session:
            existing = await session.scalar(
                select(FeedbackDatasetSnapshotRow).where(
                    FeedbackDatasetSnapshotRow.owner_id == snapshot.owner_id,
                    FeedbackDatasetSnapshotRow.manifest_digest == snapshot.manifest_digest,
                )
            )
            if existing is not None:
                return _snapshot(existing)
            row = FeedbackDatasetSnapshotRow(
                dataset_id=snapshot.dataset_id,
                owner_id=snapshot.owner_id,
                collection_id=snapshot.collection_id,
                dataset_type=snapshot.dataset_type,
                rows=deepcopy(list(snapshot.rows)),
                exclusions=deepcopy(list(snapshot.exclusions)),
                provenance=deepcopy(snapshot.provenance),
                manifest=deepcopy(snapshot.manifest),
                manifest_digest=snapshot.manifest_digest,
                provenance_digest=snapshot.provenance_digest,
                content_digest=snapshot.content_digest,
                row_count=snapshot.row_count,
                excluded_count=snapshot.excluded_count,
                created_at=_datetime(snapshot.created_at),
            )
            session.add(row)
            await session.flush()
            return _snapshot(row)

    async def read(self, dataset_id: str) -> DatasetSnapshot | None:
        async with self.session_factory() as session:
            row = await session.get(FeedbackDatasetSnapshotRow, dataset_id)
            return _snapshot(row) if row is not None else None

    async def list_for_owner(
        self,
        *,
        owner_id: str,
        collection_id: str | None = None,
        dataset_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[DatasetSnapshot, ...]:
        statement = (
            select(FeedbackDatasetSnapshotRow)
            .where(FeedbackDatasetSnapshotRow.owner_id == owner_id)
            .order_by(
                FeedbackDatasetSnapshotRow.created_at.desc(),
                FeedbackDatasetSnapshotRow.dataset_id,
            )
            .offset(offset)
            .limit(limit)
        )
        if collection_id is not None:
            statement = statement.where(
                FeedbackDatasetSnapshotRow.collection_id == collection_id
            )
        if dataset_type is not None:
            statement = statement.where(
                FeedbackDatasetSnapshotRow.dataset_type == dataset_type
            )
        async with self.session_factory() as session:
            rows = await session.scalars(statement)
            return tuple(_snapshot(row) for row in rows)


def _snapshot(row: FeedbackDatasetSnapshotRow) -> DatasetSnapshot:
    return DatasetSnapshot(
        dataset_id=row.dataset_id,
        owner_id=row.owner_id,
        collection_id=row.collection_id,
        dataset_type=row.dataset_type,  # type: ignore[arg-type]
        rows=tuple(deepcopy(row.rows or ())),
        exclusions=tuple(deepcopy(row.exclusions or ())),
        provenance=deepcopy(row.provenance or {}),
        manifest=deepcopy(row.manifest or {}),
        manifest_digest=row.manifest_digest,
        provenance_digest=row.provenance_digest,
        content_digest=row.content_digest,
        created_at=_iso(row.created_at),
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


def _iso(value: datetime) -> str:
    return _datetime(value).isoformat()


__all__ = ["PostgresDatasetSnapshotRepository"]
