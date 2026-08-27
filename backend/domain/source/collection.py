from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


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
            collection_id=str(collection_id),
            owner_user_id=_normalize_optional_text(owner_user_id) or "local-user",
            name=str(name),
            description=_normalize_optional_text(description),
            status="idle",
            created_at=str(now_iso),
            updated_at=str(now_iso),
        )

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any] | None,
        collection_id: str,
        *,
        now_iso: str,
    ) -> "Collection":
        source = dict(payload or {})
        resolved_collection_id = _normalize_optional_text(
            source.get("collection_id") or source.get("id")
        ) or str(collection_id)
        created_at = _normalize_optional_text(source.get("created_at")) or str(now_iso)
        updated_at = _normalize_optional_text(source.get("updated_at")) or created_at
        return cls(
            collection_id=resolved_collection_id,
            owner_user_id=(
                _normalize_optional_text(source.get("owner_user_id")) or "local-user"
            ),
            name=_normalize_optional_text(source.get("name")) or resolved_collection_id,
            description=_normalize_optional_text(source.get("description")),
            status=_normalize_optional_text(source.get("status")) or "idle",
            created_at=created_at,
            updated_at=updated_at,
            documents=tuple(
                item
                for item in source.get("documents") or ()
                if isinstance(item, Document)
            ),
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


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


__all__ = ["Collection", "Document"]
