from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.source import Collection, Document


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
    async def add_collection(self, collection: Collection) -> None: ...

    async def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionSummary, ...]: ...

    async def read_collection(
        self, collection_id: str
    ) -> Collection | None: ...

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> Document | None: ...

    async def update_collection(self, collection: Collection) -> bool: ...

    async def add_documents(
        self,
        collection_id: str,
        documents: tuple[Document, ...],
        *,
        updated_at: str,
    ) -> None: ...

    async def update_document(self, document: Document) -> bool: ...

    async def delete_collection(self, collection_id: str) -> bool: ...
