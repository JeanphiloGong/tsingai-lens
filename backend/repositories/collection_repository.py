"""PostgreSQL repository for collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.persistence.database import AsyncSessionLocal

from domain.source import Collection as CollectionAggregate
from domain.source import Document as DocumentAggregate
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.document_preparation import (
    DocumentPreparationRow,
)
from repositories.feedback_dataset_repository import ensure_system_datasets


@dataclass(frozen=True)
class StoredDocument:
    document: DocumentAggregate
    stored_filename: str
    storage_key: str
    created_at: str
    updated_at: str | None = None


@dataclass(frozen=True)
class StoredCollection:
    collection: CollectionAggregate
    created_at: str
    updated_at: str
    documents: tuple[StoredDocument, ...] = ()


@dataclass(frozen=True)
class CollectionDocumentSummary:
    document_id: str
    original_filename: str
    media_type: str | None
    status: str
    size_bytes: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CollectionSummary:
    collection_id: str
    name: str
    description: str | None
    status: str
    created_at: str
    updated_at: str
    documents: tuple[CollectionDocumentSummary, ...]


class CollectionRepository:
    async def add_collection(self, record: StoredCollection) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            db.add(
                Collection(
                    collection_id=record.collection.collection_id,
                    owner_user_id=record.collection.owner_user_id,
                    name=record.collection.name,
                    description=record.collection.description,
                    status=record.collection.status,
                    created_at=_datetime(record.created_at),
                    updated_at=_datetime(record.updated_at),
                )
            )
            await db.flush()
            await ensure_system_datasets(
                db, collection_id=record.collection.collection_id,
                owner_user_id=record.collection.owner_user_id,
                now=_datetime(record.created_at),
            )

    async def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionSummary, ...]:
        statement = select(
            Collection.collection_id, Collection.name, Collection.description,
            Collection.status, Collection.created_at, Collection.updated_at,
        ).order_by(Collection.created_at)
        if owner_user_id is not None:
            statement = statement.where(Collection.owner_user_id == owner_user_id)
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(statement)).all()
            if not rows:
                return ()
            documents_by_collection: dict[str, list[CollectionDocumentSummary]] = {
                row.collection_id: [] for row in rows
            }
            documents = await db.execute(
                select(
                    Document.collection_id, Document.document_id,
                    Document.original_filename, Document.media_type, Document.status,
                    Document.size_bytes, Document.created_at, Document.updated_at,
                )
                .where(Document.collection_id.in_(documents_by_collection))
                .order_by(Document.document_order)
            )
            for document in documents:
                documents_by_collection[document.collection_id].append(
                    CollectionDocumentSummary(
                        document_id=document.document_id,
                        original_filename=document.original_filename,
                        media_type=document.media_type,
                        status=document.status,
                        size_bytes=document.size_bytes,
                        created_at=_iso(document.created_at),
                        updated_at=_iso(document.updated_at),
                    )
                )
            return tuple(
                CollectionSummary(
                    collection_id=row.collection_id,
                    name=row.name,
                    description=row.description,
                    status=row.status,
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    documents=tuple(documents_by_collection[row.collection_id]),
                )
                for row in rows
            )

    async def read_collection(
        self,
        collection_id: str,
    ) -> StoredCollection | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(Collection, collection_id)
            if row is None:
                return None
            return StoredCollection(
                collection=CollectionAggregate(
                    collection_id=row.collection_id,
                    owner_user_id=row.owner_user_id,
                    name=row.name,
                    description=row.description,
                    status=row.status,
                ),
                created_at=_iso(row.created_at),
                updated_at=_iso(row.updated_at),
                documents=await load_collection_documents(db, collection_id),
            )

    async def collection_belongs_to_user(
        self, collection_id: str, owner_user_id: str
    ) -> bool:
        statement = select(Collection.collection_id).where(
            Collection.collection_id == collection_id,
            Collection.owner_user_id == owner_user_id,
        )
        async with AsyncSessionLocal() as db:
            return await db.scalar(statement) is not None

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> StoredDocument | None:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(Document, DocumentPreparationRow)
                .outerjoin(
                    DocumentPreparationRow,
                    DocumentPreparationRow.document_id == Document.document_id,
                )
                .where(
                    Document.collection_id == collection_id,
                    Document.document_id == document_id,
                )
            )).one_or_none()
            if row is None:
                return None
            document, preparation = row
            profile = dict(preparation.profile_json or {}) if preparation else {}
            source_fingerprint = preparation.source_fingerprint if preparation else None
            profile_fingerprint = profile.get("profile_fingerprint")
            return StoredDocument(
                document=DocumentAggregate(
                    document_id=document.document_id,
                    original_filename=document.original_filename,
                    sha256=document.sha256,
                    media_type=document.media_type,
                    status=document.status,
                    size_bytes=document.size_bytes,
                    parser_version=preparation.parser_version if preparation else None,
                    document_analysis_version=profile.get("profile_version"),
                    source_fingerprint=source_fingerprint,
                    profile_fingerprint=profile_fingerprint,
                    preparation_fingerprint=profile_fingerprint or source_fingerprint,
                ),
                stored_filename=document.stored_filename,
                storage_key=document.storage_key,
                created_at=_iso(document.created_at),
                updated_at=_iso(document.updated_at),
            )

    async def update_collection(self, record: StoredCollection) -> bool:
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(Collection, record.collection.collection_id)
            if row is None:
                return False
            row.owner_user_id = record.collection.owner_user_id
            row.name = record.collection.name
            row.description = record.collection.description
            row.status = record.collection.status
            row.updated_at = _datetime(record.updated_at)
            return True

    async def read_agent_default_permission(
        self, collection_id: str
    ) -> dict[str, Any] | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(Collection, collection_id)
            if row is None:
                return None
            return dict(row.agent_default_permission or {}) or None

    async def set_agent_default_permission(
        self,
        collection_id: str,
        permission: dict[str, Any],
        *,
        expected_revision: int,
    ) -> bool:
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(Collection, collection_id, with_for_update=True)
            if row is None:
                return False
            current_revision = (row.agent_default_permission or {}).get("revision", 0)
            if current_revision != expected_revision:
                raise ValueError("permission_revision_conflict")
            row.agent_default_permission = dict(permission)
            return True

    async def add_documents(
        self,
        collection_id: str,
        documents: tuple[StoredDocument, ...],
        *,
        updated_at: str,
    ) -> None:
        if not documents:
            raise ValueError("at least one document is required")
        async with AsyncSessionLocal() as db, db.begin():
            collection = await db.get(
                Collection,
                collection_id,
                with_for_update=True,
            )
            if collection is None:
                raise FileNotFoundError(f"collection not found: {collection_id}")
            existing_ids = set(
                await db.scalars(
                    select(Document.document_id).where(
                        Document.collection_id == collection_id
                    )
                )
            )
            existing_hashes = set(
                await db.scalars(
                    select(Document.sha256).where(
                        Document.collection_id == collection_id
                    )
                )
            )
            if len({item.document.document_id for item in documents}) != len(
                documents
            ) or any(item.document.document_id in existing_ids for item in documents):
                raise ValueError("document already exists")
            if len({item.document.sha256 for item in documents}) != len(
                documents
            ) or any(item.document.sha256 in existing_hashes for item in documents):
                raise ValueError("document content already exists in collection")
            next_order = int(
                await db.scalar(
                    select(func.coalesce(func.max(Document.document_order), -1)).where(
                        Document.collection_id == collection_id
                    )
                )
            ) + 1
            db.add_all(
                Document(
                    document_id=item.document.document_id,
                    collection_id=collection_id,
                    original_filename=item.document.original_filename,
                    stored_filename=item.stored_filename,
                    storage_key=item.storage_key,
                    sha256=item.document.sha256,
                    media_type=item.document.media_type,
                    status=item.document.status,
                    size_bytes=item.document.size_bytes,
                    document_order=next_order + position,
                    created_at=_datetime(item.created_at),
                    updated_at=_datetime(item.updated_at or item.created_at),
                )
                for position, item in enumerate(documents)
            )
            collection.status = "uploaded"
            collection.updated_at = _datetime(updated_at)

    async def update_document(self, record: StoredDocument) -> bool:
        async with AsyncSessionLocal() as db, db.begin():
            document = record.document
            row = await db.get(Document, document.document_id)
            if row is None:
                return False
            row.original_filename = document.original_filename
            row.stored_filename = record.stored_filename
            row.storage_key = record.storage_key
            row.sha256 = document.sha256
            row.media_type = document.media_type
            row.status = document.status
            row.size_bytes = document.size_bytes
            row.updated_at = _datetime(record.updated_at or record.created_at)
            return True

    async def delete_collection(self, collection_id: str) -> bool:
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(Collection, collection_id)
            if row is None:
                return False
            await db.delete(row)
            return True


async def load_collection_documents(
    db: AsyncSession,
    collection_id: str,
) -> tuple[StoredDocument, ...]:
    rows = await db.execute(
        select(Document, DocumentPreparationRow)
        .outerjoin(
            DocumentPreparationRow,
            DocumentPreparationRow.document_id == Document.document_id,
        )
        .where(Document.collection_id == collection_id)
        .order_by(Document.document_order)
    )
    documents = []
    for document, preparation in rows:
        profile = dict(preparation.profile_json or {}) if preparation else {}
        source_fingerprint = preparation.source_fingerprint if preparation else None
        profile_fingerprint = profile.get("profile_fingerprint")
        documents.append(StoredDocument(
            document=DocumentAggregate(
                document_id=document.document_id,
                original_filename=document.original_filename,
                sha256=document.sha256,
                media_type=document.media_type,
                status=document.status,
                size_bytes=document.size_bytes,
                parser_version=preparation.parser_version if preparation else None,
                document_analysis_version=profile.get("profile_version"),
                source_fingerprint=source_fingerprint,
                profile_fingerprint=profile_fingerprint,
                # The source identity remains usable until profiling completes.
                preparation_fingerprint=profile_fingerprint or source_fingerprint,
            ),
            stored_filename=document.stored_filename,
            storage_key=document.storage_key,
            created_at=_iso(document.created_at),
            updated_at=_iso(document.updated_at),
        ))
    return tuple(documents)


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


__all__ = ['CollectionRepository']


CollectionRepo = CollectionRepository()
