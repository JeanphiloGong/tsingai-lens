"""PostgreSQL repository for collection."""

from __future__ import annotations

from contextlib import nullcontext

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from domain.source import Collection as CollectionAggregate
from domain.source import Document as DocumentAggregate
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.collection import CollectionORM
from infra.persistence.postgres.models.document import DocumentORM
from infra.persistence.postgres.models.document_preparation import (
    DocumentPreparationORM,
)
from repositories.feedback_dataset_repository import ensure_system_datasets
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


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


class DocumentContentAlreadyExists(ValueError):
    """The collection already contains the uploaded content digest."""


class PermissionRevisionConflict(ValueError):
    """The permission revision changed before the locked write."""


class CollectionRepository:
    async def add_collection(self, record: StoredCollection) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            db.add(
                CollectionORM(
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
                db,
                collection_id=record.collection.collection_id,
                owner_user_id=record.collection.owner_user_id,
                now=_datetime(record.created_at),
            )

    async def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionSummary, ...]:
        statement = select(
            CollectionORM.collection_id,
            CollectionORM.name,
            CollectionORM.description,
            CollectionORM.status,
            CollectionORM.created_at,
            CollectionORM.updated_at,
        ).order_by(CollectionORM.created_at)
        if owner_user_id is not None:
            statement = statement.where(CollectionORM.owner_user_id == owner_user_id)
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(statement)).all()
            if not rows:
                return ()
            documents_by_collection: dict[str, list[CollectionDocumentSummary]] = {
                row.collection_id: [] for row in rows
            }
            documents = await db.execute(
                select(
                    DocumentORM.collection_id,
                    DocumentORM.document_id,
                    DocumentORM.original_filename,
                    DocumentORM.media_type,
                    DocumentORM.status,
                    DocumentORM.size_bytes,
                    DocumentORM.created_at,
                    DocumentORM.updated_at,
                )
                .where(DocumentORM.collection_id.in_(documents_by_collection))
                .order_by(DocumentORM.document_order)
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
            row = await db.get(CollectionORM, collection_id)
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
        statement = select(CollectionORM.collection_id).where(
            CollectionORM.collection_id == collection_id,
            CollectionORM.owner_user_id == owner_user_id,
        )
        async with AsyncSessionLocal() as db:
            return await db.scalar(statement) is not None

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
        *,
        db: AsyncSession | None = None,
    ) -> StoredDocument | None:
        async with AsyncSessionLocal() if db is None else nullcontext(db) as db:
            row = (
                await db.execute(
                    select(DocumentORM, DocumentPreparationORM)
                    .outerjoin(
                        DocumentPreparationORM,
                        DocumentPreparationORM.document_id == DocumentORM.document_id,
                    )
                    .where(
                        DocumentORM.collection_id == collection_id,
                        DocumentORM.document_id == document_id,
                    )
                )
            ).one_or_none()
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
            row = await db.get(CollectionORM, record.collection.collection_id)
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
            row = await db.get(CollectionORM, collection_id)
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
            row = await db.get(CollectionORM, collection_id, with_for_update=True)
            if row is None:
                return False
            current_revision = (row.agent_default_permission or {}).get("revision", 0)
            if current_revision != expected_revision:
                raise PermissionRevisionConflict("permission_revision_conflict")
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
                CollectionORM,
                collection_id,
                with_for_update=True,
            )
            if collection is None:
                raise FileNotFoundError(f"collection not found: {collection_id}")
            existing_ids = set(
                await db.scalars(
                    select(DocumentORM.document_id).where(
                        DocumentORM.collection_id == collection_id
                    )
                )
            )
            existing_hashes = set(
                await db.scalars(
                    select(DocumentORM.sha256).where(
                        DocumentORM.collection_id == collection_id
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
                raise DocumentContentAlreadyExists(
                    "document content already exists in collection"
                )
            next_order = (
                int(
                    await db.scalar(
                        select(
                            func.coalesce(func.max(DocumentORM.document_order), -1)
                        ).where(DocumentORM.collection_id == collection_id)
                    )
                )
                + 1
            )
            db.add_all(
                DocumentORM(
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

    async def update_document(
        self, record: StoredDocument, *, db: AsyncSession | None = None
    ) -> bool:
        async with AsyncSessionLocal.begin() if db is None else nullcontext(db) as db:
            document = record.document
            row = await db.get(DocumentORM, document.document_id)
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
            row = await db.get(CollectionORM, collection_id)
            if row is None:
                return False
            await db.delete(row)
            return True


async def load_collection_documents(
    db: AsyncSession,
    collection_id: str,
) -> tuple[StoredDocument, ...]:
    rows = await db.execute(
        select(DocumentORM, DocumentPreparationORM)
        .outerjoin(
            DocumentPreparationORM,
            DocumentPreparationORM.document_id == DocumentORM.document_id,
        )
        .where(DocumentORM.collection_id == collection_id)
        .order_by(DocumentORM.document_order)
    )
    documents = []
    for document, preparation in rows:
        profile = dict(preparation.profile_json or {}) if preparation else {}
        source_fingerprint = preparation.source_fingerprint if preparation else None
        profile_fingerprint = profile.get("profile_fingerprint")
        documents.append(
            StoredDocument(
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
            )
        )
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


__all__ = ["CollectionRepository"]


CollectionRepo = CollectionRepository()
