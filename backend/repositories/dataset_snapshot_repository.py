"""PostgreSQL repository for dataset snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from infra.persistence.database import AsyncSessionLocal

from domain.feedback.dataset_snapshot import DatasetSnapshot
from infra.persistence.postgres.models.feedback import FeedbackDatasetSnapshotRow


class DatasetSnapshotRepository:
    backend_name = "postgresql"

    async def save(self, snapshot: DatasetSnapshot) -> DatasetSnapshot:
        async with AsyncSessionLocal() as db, db.begin():
            existing = await db.scalar(
                select(FeedbackDatasetSnapshotRow).where(
                    FeedbackDatasetSnapshotRow.owner_id == snapshot.owner_id,
                    FeedbackDatasetSnapshotRow.manifest_digest
                    == snapshot.manifest_digest,
                )
            )
            if existing is not None:
                return DatasetSnapshot(
                    dataset_id=existing.dataset_id,
                    owner_id=existing.owner_id,
                    collection_id=existing.collection_id,
                    dataset_type=existing.dataset_type,
                    rows=tuple(existing.rows),
                    exclusions=tuple(existing.exclusions),
                    provenance=existing.provenance,
                    manifest=existing.manifest,
                    manifest_digest=existing.manifest_digest,
                    provenance_digest=existing.provenance_digest,
                    content_digest=existing.content_digest,
                    created_at=_iso(existing.created_at),
                )
            row = FeedbackDatasetSnapshotRow(
                dataset_id=snapshot.dataset_id,
                owner_id=snapshot.owner_id,
                collection_id=snapshot.collection_id,
                dataset_type=snapshot.dataset_type,
                rows=list(snapshot.rows),
                exclusions=list(snapshot.exclusions),
                provenance=snapshot.provenance,
                manifest=snapshot.manifest,
                manifest_digest=snapshot.manifest_digest,
                provenance_digest=snapshot.provenance_digest,
                content_digest=snapshot.content_digest,
                row_count=snapshot.row_count,
                excluded_count=snapshot.excluded_count,
                created_at=_datetime(snapshot.created_at),
            )
            db.add(row)
            await db.flush()
            return DatasetSnapshot(
                dataset_id=row.dataset_id,
                owner_id=row.owner_id,
                collection_id=row.collection_id,
                dataset_type=row.dataset_type,
                rows=tuple(row.rows),
                exclusions=tuple(row.exclusions),
                provenance=row.provenance,
                manifest=row.manifest,
                manifest_digest=row.manifest_digest,
                provenance_digest=row.provenance_digest,
                content_digest=row.content_digest,
                created_at=_iso(row.created_at),
            )

    async def read(self, dataset_id: str) -> DatasetSnapshot | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(FeedbackDatasetSnapshotRow, dataset_id)
            return (
                DatasetSnapshot(
                    dataset_id=row.dataset_id,
                    owner_id=row.owner_id,
                    collection_id=row.collection_id,
                    dataset_type=row.dataset_type,
                    rows=tuple(row.rows),
                    exclusions=tuple(row.exclusions),
                    provenance=row.provenance,
                    manifest=row.manifest,
                    manifest_digest=row.manifest_digest,
                    provenance_digest=row.provenance_digest,
                    content_digest=row.content_digest,
                    created_at=_iso(row.created_at),
                )
                if row is not None
                else None
            )

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
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(statement)
            return tuple(
                DatasetSnapshot(
                    dataset_id=row.dataset_id,
                    owner_id=row.owner_id,
                    collection_id=row.collection_id,
                    dataset_type=row.dataset_type,
                    rows=tuple(row.rows),
                    exclusions=tuple(row.exclusions),
                    provenance=row.provenance,
                    manifest=row.manifest,
                    manifest_digest=row.manifest_digest,
                    provenance_digest=row.provenance_digest,
                    content_digest=row.content_digest,
                    created_at=_iso(row.created_at),
                )
                for row in rows
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


__all__ = ["DatasetSnapshotRepository"]
