from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..source.collection import CollectionResponse
from ..source.task import TaskResponse


WorkflowStageStatus = Literal[
    "not_started",
    "processing",
    "ready",
    "failed",
]


class WorkspaceArtifactStatusResponse(BaseModel):
    """Readiness of the maintained collection-build outputs."""

    source_documents_ready: bool = False
    document_profiles_ready: bool = False
    objective_candidates_ready: bool = False
    updated_at: str


class WorkspaceStageResponse(BaseModel):
    """Readiness of one maintained research step."""

    status: WorkflowStageStatus
    detail: str


class WorkspaceWorkflowResponse(BaseModel):
    """Research steps exposed by the collection workspace."""

    documents: WorkspaceStageResponse
    objectives: WorkspaceStageResponse


class WorkspaceDocumentSummaryResponse(BaseModel):
    """Collection-level document profile rollup."""

    total_documents: int = 0
    by_doc_type: dict[str, int] = Field(default_factory=dict)


class WorkspaceWarningResponse(BaseModel):
    """Collection-facing warning derived from document profiles."""

    code: str
    severity: Literal["info", "warning", "error"]
    message: str


class WorkspaceCapabilitiesResponse(BaseModel):
    """Maintained collection surfaces that currently have data."""

    can_view_documents: bool = False
    can_view_objectives: bool = False
    can_view_comparisons: bool = False


class WorkspaceLinksResponse(BaseModel):
    """Browser routes for maintained collection surfaces."""

    workspace: str
    documents: str
    objectives: str
    comparisons: str


class WorkspaceOverviewResponse(BaseModel):
    """Top-level collection workspace payload."""

    collection: CollectionResponse
    file_count: int = 0
    status_summary: str
    artifacts: WorkspaceArtifactStatusResponse
    workflow: WorkspaceWorkflowResponse
    document_summary: WorkspaceDocumentSummaryResponse = Field(
        default_factory=WorkspaceDocumentSummaryResponse
    )
    warnings: list[WorkspaceWarningResponse] = Field(default_factory=list)
    latest_task: TaskResponse | None = None
    recent_tasks: list[TaskResponse] = Field(default_factory=list)
    capabilities: WorkspaceCapabilitiesResponse
    links: WorkspaceLinksResponse
