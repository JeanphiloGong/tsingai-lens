"""PostgreSQL persistence for collections and their current documents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.source import Collection as CollectionAggregate
from domain.source import Document as DocumentAggregate
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.document import Document


class PostgresCollectionRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.session_factory = session_factory

    async def add_collection(self, record: CollectionAggregate) -> None:
        async with self.session_factory.begin() as session:
            session.add(
                Collection(
                    collection_id=record.collection_id,
                    owner_user_id=record.owner_user_id,
                    name=record.name,
                    description=record.description,
                    status=record.status,
                    paper_count=0,
                    created_at=_datetime(record.created_at),
                    updated_at=_datetime(record.updated_at),
                )
            )

    async def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionAggregate, ...]:
        statement = select(Collection).order_by(Collection.created_at)
        if owner_user_id is not None:
            statement = statement.where(Collection.owner_user_id == owner_user_id)
        async with self.session_factory() as session:
            rows = tuple(await session.scalars(statement))
            collections: list[CollectionAggregate] = []
            for row in rows:
                documents = await _documents_for_collection(
                    session,
                    row.collection_id,
                )
                collections.append(_to_collection(row, documents))
            return tuple(collections)

    async def read_collection(
        self,
        collection_id: str,
    ) -> CollectionAggregate | None:
        async with self.session_factory() as session:
            row = await session.get(Collection, collection_id)
            if row is None:
                return None
            return _to_collection(
                row,
                await _documents_for_collection(session, collection_id),
            )

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentAggregate | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(Document).where(
                    Document.collection_id == collection_id,
                    Document.document_id == document_id,
                )
            )
            return _to_document(row) if row is not None else None

    async def update_collection(self, record: CollectionAggregate) -> bool:
        async with self.session_factory.begin() as session:
            row = await session.get(Collection, record.collection_id)
            if row is None:
                return False
            row.owner_user_id = record.owner_user_id
            row.name = record.name
            row.description = record.description
            row.status = record.status
            row.paper_count = len(record.documents)
            row.updated_at = _datetime(record.updated_at)
            return True

    async def add_documents(
        self,
        collection_id: str,
        documents: tuple[DocumentAggregate, ...],
        *,
        updated_at: str,
    ) -> None:
        if not documents:
            raise ValueError("at least one document is required")
        async with self.session_factory.begin() as session:
            collection = await session.get(
                Collection,
                collection_id,
                with_for_update=True,
            )
            if collection is None:
                raise FileNotFoundError(f"collection not found: {collection_id}")
            existing_ids = set(
                await session.scalars(
                    select(Document.document_id).where(
                        Document.collection_id == collection_id
                    )
                )
            )
            existing_hashes = set(
                await session.scalars(
                    select(Document.sha256).where(
                        Document.collection_id == collection_id
                    )
                )
            )
            if len({item.document_id for item in documents}) != len(documents) or any(
                item.document_id in existing_ids for item in documents
            ):
                raise ValueError("document already exists")
            if len({item.sha256 for item in documents}) != len(documents) or any(
                item.sha256 in existing_hashes for item in documents
            ):
                raise ValueError("document content already exists in collection")
            next_order = int(
                await session.scalar(
                    select(func.coalesce(func.max(Document.document_order), -1)).where(
                        Document.collection_id == collection_id
                    )
                )
            ) + 1
            session.add_all(
                _document_row(collection_id, item, next_order + position)
                for position, item in enumerate(documents)
            )
            collection.paper_count = len(existing_ids) + len(documents)
            collection.status = "uploaded"
            collection.updated_at = _datetime(updated_at)

    async def update_document(self, record: DocumentAggregate) -> bool:
        async with self.session_factory.begin() as session:
            row = await session.get(Document, record.document_id)
            if row is None:
                return False
            row.original_filename = record.original_filename
            row.stored_filename = record.stored_filename
            row.storage_key = record.storage_key
            row.sha256 = record.sha256
            row.media_type = record.media_type
            row.status = record.status
            row.size_bytes = record.size_bytes
            row.parser_version = record.parser_version
            row.document_analysis_version = record.document_analysis_version
            row.source_fingerprint = record.source_fingerprint
            row.profile_fingerprint = record.profile_fingerprint
            row.preparation_fingerprint = record.preparation_fingerprint
            row.updated_at = _datetime(record.updated_at or record.created_at)
            return True

    async def delete_collection(self, collection_id: str) -> bool:
        async with self.session_factory.begin() as session:
            row = await session.get(Collection, collection_id)
            if row is None:
                return False
            await session.delete(row)
            return True


def _to_collection(
    row: Collection,
    documents: tuple[DocumentAggregate, ...],
) -> CollectionAggregate:
    return CollectionAggregate(
        collection_id=row.collection_id,
        owner_user_id=row.owner_user_id,
        name=row.name,
        description=row.description,
        status=row.status,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        documents=documents,
    )


def _document_row(
    collection_id: str,
    record: DocumentAggregate,
    document_order: int,
) -> Document:
    return Document(
        document_id=record.document_id,
        collection_id=collection_id,
        original_filename=record.original_filename,
        stored_filename=record.stored_filename,
        storage_key=record.storage_key,
        sha256=record.sha256,
        media_type=record.media_type,
        status=record.status,
        size_bytes=record.size_bytes,
        document_order=document_order,
        parser_version=record.parser_version,
        document_analysis_version=record.document_analysis_version,
        source_fingerprint=record.source_fingerprint,
        profile_fingerprint=record.profile_fingerprint,
        preparation_fingerprint=record.preparation_fingerprint,
        created_at=_datetime(record.created_at),
        updated_at=_datetime(record.updated_at or record.created_at),
    )


def _to_document(row: Document) -> DocumentAggregate:
    return DocumentAggregate(
        document_id=row.document_id,
        original_filename=row.original_filename,
        stored_filename=row.stored_filename,
        storage_key=row.storage_key,
        sha256=row.sha256,
        media_type=row.media_type,
        status=row.status,
        size_bytes=row.size_bytes,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        parser_version=row.parser_version,
        document_analysis_version=row.document_analysis_version,
        source_fingerprint=row.source_fingerprint,
        profile_fingerprint=row.profile_fingerprint,
        preparation_fingerprint=row.preparation_fingerprint,
    )


async def _documents_for_collection(
    session: AsyncSession,
    collection_id: str,
) -> tuple[DocumentAggregate, ...]:
    rows = await session.scalars(
        select(Document)
        .where(Document.collection_id == collection_id)
        .order_by(Document.document_order)
    )
    return tuple(_to_document(row) for row in rows)


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
