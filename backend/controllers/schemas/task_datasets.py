"""HTTP contracts for maintained task-specific feedback datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DatasetTaskTypeLiteral = Literal["sft", "preference", "evaluation"]


class TaskDatasetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    # D1 only opens SFT creation.  D6 widens this request after its builders
    # and annotation screens exist.
    task_type: Literal["sft"]
    construction_spec: dict[str, Any] = Field(default_factory=dict)


class TaskDatasetResponse(BaseModel):
    dataset_id: str
    collection_id: str
    name: str
    task_type: DatasetTaskTypeLiteral
    construction_spec: dict[str, Any]
    spec_version: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class TaskDatasetListResponse(BaseModel):
    items: list[TaskDatasetResponse]
    limit: int
    offset: int


__all__ = [
    "TaskDatasetCreateRequest",
    "TaskDatasetListResponse",
    "TaskDatasetResponse",
]
