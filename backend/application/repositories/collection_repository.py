from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from domain.source import Collection, Document


@dataclass(frozen=True)
class StoredDocument:
    document: Document
    stored_filename: str
    storage_key: str
    created_at: str
    updated_at: str | None = None


@dataclass(frozen=True)
class StoredCollection:
    collection: Collection
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


class CollectionRepository(Protocol):

    async def add_collection(self, collection: StoredCollection) -> None: ...

    async def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionSummary, ...]: ...

    async def read_collection(self, collection_id: str) -> StoredCollection | None: ...

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> StoredDocument | None: ...

    async def update_collection(self, collection: StoredCollection) -> bool: ...

    async def read_agent_default_permission(
        self, collection_id: str
    ) -> dict[str, Any] | None: ...

    async def set_agent_default_permission(
        self,
        collection_id: str,
        permission: dict[str, Any],
        *,
        expected_revision: int,
    ) -> bool: ...

    async def add_documents(
        self,
        collection_id: str,
        documents: tuple[StoredDocument, ...],
        *,
        updated_at: str,
    ) -> None: ...

    async def update_document(self, document: StoredDocument) -> bool: ...

    async def delete_collection(self, collection_id: str) -> bool: ...
