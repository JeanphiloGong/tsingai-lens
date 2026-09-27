"""Immutable, user-created exports of reviewed feedback cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


DatasetType = Literal["evaluation", "sft", "preference"]
DatasetSplit = Literal["train", "eval"]

_DATASET_TYPES = {"evaluation", "sft", "preference"}
_SPLITS = {"train", "eval"}


@dataclass(frozen=True)
class DatasetSnapshot:
    """A frozen export whose rows never follow later case changes."""

    dataset_id: str
    owner_id: str
    collection_id: str
    dataset_type: DatasetType
    rows: tuple[dict[str, Any], ...]
    exclusions: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]
    manifest: dict[str, Any]
    manifest_digest: str
    provenance_digest: str
    content_digest: str
    created_at: str

    def __post_init__(self) -> None:
        if not self.dataset_id or not self.owner_id or not self.collection_id:
            raise ValueError("dataset snapshot identity is required")
        if self.dataset_type not in _DATASET_TYPES:
            raise ValueError("invalid dataset type")
        if len(self.manifest_digest) != 64:
            raise ValueError("manifest digest must be sha256")
        if len(self.provenance_digest) != 64:
            raise ValueError("provenance digest must be sha256")
        if len(self.content_digest) != 64:
            raise ValueError("content digest must be sha256")
        for row in self.rows:
            if not isinstance(row, dict) or row.get("split") not in _SPLITS:
                raise ValueError("snapshot rows require train or eval split")
            if row.get("record_type") not in _DATASET_TYPES:
                raise ValueError("snapshot rows require a dataset record type")
        object.__setattr__(self, "rows", tuple(dict(row) for row in self.rows))
        object.__setattr__(self, "exclusions", tuple(dict(item) for item in self.exclusions))
        object.__setattr__(self, "provenance", dict(self.provenance))
        object.__setattr__(self, "manifest", dict(self.manifest))

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def excluded_count(self) -> int:
        return len(self.exclusions)

    @property
    def is_empty(self) -> bool:
        return not self.rows

    def to_record(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "owner_id": self.owner_id,
            "collection_id": self.collection_id,
            "dataset_type": self.dataset_type,
            "rows": [dict(row) for row in self.rows],
            "exclusions": [dict(item) for item in self.exclusions],
            "provenance": dict(self.provenance),
            "manifest": dict(self.manifest),
            "manifest_digest": self.manifest_digest,
            "provenance_digest": self.provenance_digest,
            "content_digest": self.content_digest,
            "row_count": self.row_count,
            "excluded_count": self.excluded_count,
            "is_empty": self.is_empty,
            "created_at": self.created_at,
        }


__all__ = ["DatasetSnapshot", "DatasetSplit", "DatasetType"]
