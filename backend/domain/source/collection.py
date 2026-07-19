from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class CollectionRecord:
    collection_id: str
    owner_user_id: str
    name: str
    description: str | None
    status: str
    paper_count: int
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        *,
        collection_id: str,
        owner_user_id: str = "local-user",
        name: str,
        description: str | None,
        now_iso: str,
    ) -> "CollectionRecord":
        return cls(
            collection_id=str(collection_id),
            owner_user_id=_normalize_optional_text(owner_user_id) or "local-user",
            name=str(name),
            description=_normalize_optional_text(description),
            status="idle",
            paper_count=0,
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
    ) -> "CollectionRecord":
        source = dict(payload or {})
        resolved_collection_id = _normalize_optional_text(
            source.get("collection_id") or source.get("id")
        ) or str(collection_id)
        created_at = _normalize_optional_text(source.get("created_at")) or str(now_iso)
        updated_at = _normalize_optional_text(source.get("updated_at")) or created_at
        name = _normalize_optional_text(source.get("name")) or resolved_collection_id
        owner_user_id = (
            _normalize_optional_text(source.get("owner_user_id")) or "local-user"
        )
        description = _normalize_optional_text(source.get("description"))
        status = _normalize_optional_text(source.get("status")) or "idle"
        paper_count = _normalize_non_negative_int(source.get("paper_count"))
        return cls(
            collection_id=resolved_collection_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            status=status,
            paper_count=paper_count,
            created_at=created_at,
            updated_at=updated_at,
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
        }


@dataclass(frozen=True)
class CollectionFileRecord:
    file_id: str
    collection_id: str
    object_id: str
    object_kind: str
    original_filename: str
    stored_filename: str
    storage_key: str
    sha256: str
    media_type: str | None
    status: str
    size_bytes: int
    created_at: str
    document_id: str | None = None

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "file_id": self.file_id,
            "collection_id": self.collection_id,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "storage_key": self.storage_key,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "status": self.status,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
        }
        if self.document_id is not None:
            record["document_id"] = self.document_id
        return record


@dataclass(frozen=True)
class CollectionImportDocumentRecord:
    source_document_id: str
    origin_channel: str
    file: CollectionFileRecord
    language: str | None
    ingest_status: str
    text_units: tuple[Mapping[str, Any], ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "source_document_id": self.source_document_id,
            "origin_channel": self.origin_channel,
            "original_filename": self.file.original_filename,
            "stored_filename": self.file.stored_filename,
            "storage_key": self.file.storage_key,
            "sha256": self.file.sha256,
            "media_type": self.file.media_type,
            "language": self.language,
            "ingest_status": self.ingest_status,
            "text_units": [dict(item) for item in self.text_units],
        }


@dataclass(frozen=True)
class CollectionImportRecord:
    import_id: str
    collection_id: str
    channel: str
    adapter_name: str
    adapter_version: str | None
    raw_locator: str | None
    goal_context: Mapping[str, Any] | None
    warnings: tuple[str, ...]
    ingested_at: str
    documents: tuple[CollectionImportDocumentRecord, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "channel": self.channel,
            "adapter_name": self.adapter_name,
            "adapter_version": self.adapter_version,
            "raw_locator": self.raw_locator,
            "goal_context": dict(self.goal_context)
            if self.goal_context is not None
            else None,
            "warnings": list(self.warnings),
            "ingested_at": self.ingested_at,
            "documents": [document.to_record() for document in self.documents],
        }


@dataclass(frozen=True)
class CollectionHandoffRecord:
    handoff_id: str
    collection_id: str
    kind: str
    status: str
    created_at: str
    source_channels: tuple[str, ...]
    goal_context: Mapping[str, Any]

    def to_record(self) -> dict[str, Any]:
        return {
            "handoff_id": self.handoff_id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "source_channels": list(self.source_channels),
            "goal_context": dict(self.goal_context),
        }


def empty_import_manifest(collection_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "collection_id": str(collection_id),
        "handoffs": [],
        "imports": [],
    }


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _normalize_non_negative_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, float) and math.isnan(value):
            return 0
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "CollectionFileRecord",
    "CollectionHandoffRecord",
    "CollectionImportDocumentRecord",
    "CollectionImportRecord",
    "CollectionRecord",
    "empty_import_manifest",
]
