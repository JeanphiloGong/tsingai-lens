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


class DatasetCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_case_ids: list[str] = Field(min_length=1, max_length=1000)


class DatasetCollectionItemResponse(BaseModel):
    sample_id: str
    source_case_id: str
    status: str
    job_id: str | None = None


class DatasetCollectionResponse(BaseModel):
    operation_id: str
    created_count: int
    existing_count: int
    items: list[DatasetCollectionItemResponse]


class SftRevisionContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["literature-sft.v1"]
    messages: list[dict[str, str]] = Field(min_length=1, max_length=100)
    context: list[dict[str, str]] = Field(min_length=1, max_length=1000)
    target: str = Field(min_length=1, max_length=100000)
    evidence: list[dict[str, str]] = Field(min_length=1, max_length=1000)


class SampleRevisionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: str = Field(min_length=1, max_length=64)
    content: SftRevisionContentRequest


class SampleConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: str = Field(min_length=1, max_length=64)


class DatasetSampleSummaryResponse(BaseModel):
    sample_id: str
    dataset_id: str
    source_case_id: str
    status: str
    current_revision_id: str | None
    confirmed_revision_id: str | None
    generation: int
    missing_reasons: list[str]
    created_at: str
    updated_at: str
    confirmed_by: str | None = None
    confirmed_at: str | None = None


class DatasetSampleListResponse(BaseModel):
    items: list[DatasetSampleSummaryResponse]
    total: int
    limit: int
    offset: int


class DatasetSampleRevisionResponse(BaseModel):
    revision_id: str
    sample_id: str
    revision_no: int
    author_kind: str
    content: dict[str, Any]
    content_digest: str
    input_digest: str
    construction_spec_version: int
    provenance: dict[str, Any]
    created_at: str
    created_by: str | None
    job_id: str | None


class DatasetSampleSourceCaseResponse(BaseModel):
    case_id: str
    collection_id: str
    session_id: str
    anchor_message_id: str
    status: str
    question: str = ""
    answer: str = ""
    requested_scope: list[dict[str, Any]] = Field(default_factory=list)
    inspected_sources: list[dict[str, Any]] = Field(default_factory=list)
    omitted_candidates: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    context_snapshot: dict[str, Any] = Field(default_factory=dict)


class DatasetSampleDetailResponse(BaseModel):
    sample: DatasetSampleSummaryResponse
    source_case: DatasetSampleSourceCaseResponse
    current_revision: DatasetSampleRevisionResponse | None
    confirmed_revision: DatasetSampleRevisionResponse | None


__all__ = [
    "TaskDatasetCreateRequest",
    "TaskDatasetListResponse",
    "TaskDatasetResponse",
    "DatasetCollectionItemResponse",
    "DatasetCollectionRequest",
    "DatasetCollectionResponse",
    "DatasetSampleDetailResponse",
    "DatasetSampleListResponse",
    "DatasetSampleRevisionResponse",
    "DatasetSampleSourceCaseResponse",
    "DatasetSampleSummaryResponse",
    "SampleConfirmRequest",
    "SampleRevisionUpdateRequest",
    "SftRevisionContentRequest",
]
