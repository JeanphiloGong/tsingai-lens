from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Document:
    document_id: str
    original_filename: str
    stored_filename: str
    storage_key: str
    sha256: str
    media_type: str | None
    status: str
    size_bytes: int
    created_at: str
    updated_at: str | None = None
    parser_version: str | None = None
    document_analysis_version: str | None = None
    source_fingerprint: str | None = None
    profile_fingerprint: str | None = None
    preparation_fingerprint: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "storage_key": self.storage_key,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "status": self.status,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "updated_at": self.updated_at or self.created_at,
            "parser_version": self.parser_version,
            "document_analysis_version": self.document_analysis_version,
            "source_fingerprint": self.source_fingerprint,
            "profile_fingerprint": self.profile_fingerprint,
            "preparation_fingerprint": self.preparation_fingerprint,
        }


@dataclass(frozen=True)
class Collection:
    collection_id: str
    owner_user_id: str
    name: str
    description: str | None
    status: str
    created_at: str
    updated_at: str
    documents: tuple[Document, ...] = ()

    @property
    def paper_count(self) -> int:
        return len(self.documents)

    @classmethod
    def create(
        cls,
        *,
        collection_id: str,
        owner_user_id: str = "local-user",
        name: str,
        description: str | None,
        now_iso: str,
    ) -> "Collection":
        return cls(
            collection_id=collection_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            status="idle",
            created_at=now_iso,
            updated_at=now_iso,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "owner_user_id": self.owner_user_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "paper_count": self.paper_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "documents": [document.to_record() for document in self.documents],
        }

__all__ = ["Collection", "Document"]
