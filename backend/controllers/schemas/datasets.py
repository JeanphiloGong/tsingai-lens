"""HTTP contracts for feedback dataset snapshots."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DatasetTypeLiteral = Literal["evaluation", "sft", "preference"]


class DatasetSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1, max_length=64)


class DatasetSnapshotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_id: str = Field(min_length=1, max_length=64)
    dataset_type: DatasetTypeLiteral
    items: list[DatasetSelectionRequest] = Field(default_factory=list, max_length=500)


class DatasetSnapshotResponse(BaseModel):
    dataset_id: str
    owner_id: str
    collection_id: str
    dataset_type: DatasetTypeLiteral
    rows: list[dict[str, Any]] = Field(default_factory=list)
    exclusions: list[dict[str, Any]] = Field(default_factory=list)
    provenance: dict[str, Any]
    manifest: dict[str, Any]
    manifest_digest: str
    provenance_digest: str
    content_digest: str
    row_count: int
    excluded_count: int
    is_empty: bool
    created_at: str


class DatasetSnapshotSummaryResponse(BaseModel):
    dataset_id: str
    collection_id: str
    dataset_type: DatasetTypeLiteral
    manifest_digest: str
    provenance_digest: str
    content_digest: str
    row_count: int
    excluded_count: int
    is_empty: bool
    created_at: str


class DatasetSnapshotListResponse(BaseModel):
    items: list[DatasetSnapshotSummaryResponse]
    limit: int
    offset: int


__all__ = [
    "DatasetSelectionRequest",
    "DatasetSnapshotCreateRequest",
    "DatasetSnapshotListResponse",
    "DatasetSnapshotResponse",
    "DatasetSnapshotSummaryResponse",
]
