"""Long-lived, task-specific feedback dataset definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

DatasetTaskType = Literal["sft", "preference", "evaluation"]
DATASET_TASK_TYPES = frozenset({"sft", "preference", "evaluation"})


@dataclass
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

    def __post_init__(self) -> None:
        if not self.dataset_id or not self.collection_id or not self.created_by:
            raise ValueError("dataset identity is required")
        if self.spec_version < 1:
            raise ValueError("dataset spec version must be positive")

__all__ = ["DATASET_TASK_TYPES", "Dataset", "DatasetTaskType"]
