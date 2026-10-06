"""HTTP contracts for maintained task-specific feedback datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

DatasetTaskTypeLiteral = Literal["sft", "preference", "evaluation"]


class TaskDatasetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    task_type: DatasetTaskTypeLiteral
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


class DatasetExportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_ids: list[str] | None = Field(default=None, min_length=1, max_length=1000)


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


class PreferenceRevisionContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["literature-preference.v1"]
    messages: list[dict[str, str]] = Field(min_length=1, max_length=100)
    context: list[dict[str, str]] = Field(min_length=1, max_length=1000)
    response_a: str = Field(min_length=1, max_length=100000)
    response_b: str = Field(min_length=1, max_length=100000)
    suggested_preference: Literal["a", "b", "tie", "unclear"] | None = None
    rationale: str = Field(default="", max_length=100000)
    evidence: list[dict[str, str]] = Field(min_length=1, max_length=1000)
    human_preference: Literal["a", "b", "tie", "unclear"] | None = None


class EvaluationRevisionContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["literature-evaluation.v1"]
    messages: list[dict[str, str]] = Field(min_length=1, max_length=100)
    context: list[dict[str, str]] = Field(min_length=1, max_length=1000)
    reference: str = Field(default="", max_length=100000)
    criteria: list[str] = Field(min_length=1, max_length=100)
    evaluation_mode: Literal["reference", "rubric"] = "reference"
    evidence: list[dict[str, str]] = Field(min_length=1, max_length=1000)


RevisionContentRequest = Annotated[
    Union[
        SftRevisionContentRequest,
        PreferenceRevisionContentRequest,
        EvaluationRevisionContentRequest,
    ],
    Field(discriminator="schema_version"),
]


class SampleRevisionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: str | None = Field(max_length=64)
    expected_generation: int | None = Field(default=None, ge=1)
    content: RevisionContentRequest


class SampleConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: str = Field(min_length=1, max_length=64)


class SampleActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["rebuild", "retry", "discard", "restore"]
    expected_revision_id: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=2000)


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


class DatasetExportIssueResponse(BaseModel):
    sample_id: str
    revision_id: str | None
    code: str
    message: str
    question: str


class DatasetExportPreviewRowResponse(BaseModel):
    sample_id: str
    question: str
    schema_version: str = ""
    target_preview: str = ""
    response_a_preview: str = ""
    response_b_preview: str = ""
    reference_preview: str = ""
    human_preference: str | None = None
    evidence_count: int
    issue_codes: list[str]


class DatasetExportPreviewResponse(BaseModel):
    preview_id: str
    dataset_id: str
    requested_count: int
    exportable_count: int
    issues: list[DatasetExportIssueResponse]
    sample_rows: list[DatasetExportPreviewRowResponse]
    preview_digest: str
    created_at: str
    expires_at: str


class DatasetExportPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: str = Field(min_length=1, max_length=64)
    preview_digest: str = Field(min_length=64, max_length=64)
    allow_partial: bool = False


class DatasetExportSummaryResponse(BaseModel):
    export_id: str
    dataset_id: str
    export_no: int
    schema_version: str
    row_count: int
    content_digest: str
    provenance_digest: str
    manifest_digest: str
    created_at: str
    download_formats: list[str] = ["jsonl", "json", "provenance", "manifest"]


class DatasetExportListResponse(BaseModel):
    items: list[DatasetExportSummaryResponse]
    limit: int
    offset: int


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
    "SampleActionRequest",
    "SampleRevisionUpdateRequest",
    "SftRevisionContentRequest",
    "PreferenceRevisionContentRequest",
    "EvaluationRevisionContentRequest",
    "RevisionContentRequest",
    "DatasetExportIssueResponse",
    "DatasetExportPreviewRowResponse",
    "DatasetExportPreviewResponse",
    "DatasetExportPublishRequest",
    "DatasetExportSummaryResponse",
    "DatasetExportListResponse",
]
