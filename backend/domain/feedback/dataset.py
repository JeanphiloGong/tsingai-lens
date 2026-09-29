"""Long-lived, task-specific feedback dataset definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


DatasetTaskType = Literal["sft", "preference", "evaluation"]
DATASET_TASK_TYPES = frozenset({"sft", "preference", "evaluation"})


@dataclass(frozen=True)
class Dataset:
    """A maintained dataset scoped to one collection.

    Dataset identity and task type are intentionally separate from immutable
    exports.  Samples and revisions are added by later dataset-task stages.
    """

    dataset_id: str
    collection_id: str
    name: str
    task_type: DatasetTaskType
    construction_spec: dict[str, Any]
    spec_version: int
    created_by: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        cleaned = self.name.strip()
        if not self.dataset_id or not self.collection_id or not self.created_by:
            raise ValueError("dataset identity is required")
        if not cleaned or len(cleaned) > 120:
            raise ValueError("dataset name must contain 1..120 characters")
        if self.task_type not in DATASET_TASK_TYPES:
            raise ValueError("invalid dataset task type")
        if self.spec_version < 1:
            raise ValueError("dataset spec version must be positive")
        if not isinstance(self.construction_spec, dict):
            raise ValueError("construction spec must be an object")
        object.__setattr__(self, "name", cleaned)
        object.__setattr__(self, "construction_spec", dict(self.construction_spec))

    def to_record(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "collection_id": self.collection_id,
            "name": self.name,
            "task_type": self.task_type,
            "construction_spec": dict(self.construction_spec),
            "spec_version": self.spec_version,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


__all__ = ["DATASET_TASK_TYPES", "Dataset", "DatasetTaskType"]
