from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class CollectionRecord:
    collection_id: str
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
        name: str,
        description: str | None,
        now_iso: str,
    ) -> "CollectionRecord":
        return cls(
            collection_id=str(collection_id),
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
        description = _normalize_optional_text(source.get("description"))
        status = _normalize_optional_text(source.get("status")) or "idle"
        paper_count = _normalize_non_negative_int(source.get("paper_count"))
        return cls(
            collection_id=resolved_collection_id,
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
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "paper_count": self.paper_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
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
    "CollectionRecord",
    "empty_import_manifest",
]
