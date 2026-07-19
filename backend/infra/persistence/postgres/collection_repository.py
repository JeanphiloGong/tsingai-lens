"""PostgreSQL persistence for collection metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from domain.source import CollectionRecord
from infra.persistence.postgres.models.collection import Collection


class PostgresCollectionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def add_collection(self, record: CollectionRecord) -> None:
        with self.session_factory.begin() as session:
            session.add(
                Collection(
                    collection_id=record.collection_id,
                    owner_user_id=record.owner_user_id,
                    name=record.name,
                    description=record.description,
                    status=record.status,
                    paper_count=record.paper_count,
                    created_at=_datetime(record.created_at),
                    updated_at=_datetime(record.updated_at),
                )
            )

    def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionRecord, ...]:
        statement = select(Collection).order_by(Collection.collection_id)
        if owner_user_id is not None:
            statement = statement.where(Collection.owner_user_id == owner_user_id)
        with self.session_factory() as session:
            return tuple(_to_record(row) for row in session.scalars(statement))

    def read_collection(self, collection_id: str) -> CollectionRecord | None:
        with self.session_factory() as session:
            row = session.get(Collection, collection_id)
            return _to_record(row) if row is not None else None

    def update_collection(self, record: CollectionRecord) -> bool:
        with self.session_factory.begin() as session:
            row = session.get(Collection, record.collection_id)
            if row is None:
                return False
            row.owner_user_id = record.owner_user_id
            row.name = record.name
            row.description = record.description
            row.status = record.status
            row.paper_count = record.paper_count
            row.created_at = _datetime(record.created_at)
            row.updated_at = _datetime(record.updated_at)
            return True

    def delete_collection(self, collection_id: str) -> bool:
        with self.session_factory.begin() as session:
            row = session.get(Collection, collection_id)
            if row is None:
                return False
            session.delete(row)
            return True


def _to_record(row: Collection) -> CollectionRecord:
    return CollectionRecord(
        collection_id=row.collection_id,
        owner_user_id=row.owner_user_id,
        name=row.name,
        description=row.description,
        status=row.status,
        paper_count=row.paper_count,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
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


__all__ = ["PostgresCollectionRepository"]
