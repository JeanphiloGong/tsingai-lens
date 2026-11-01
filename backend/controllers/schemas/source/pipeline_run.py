from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from application.pipeline.pipeline_run_service import document_preparation_error_message
from repositories.pipeline_run_repository import PipelineRun, PipelineRunSummary

from pydantic import BaseModel, Field


PipelineRunStatus = Literal[
    "queued", "running", "completed", "partial_success", "failed"
]
PipelineNodeStatus = Literal["queued", "running", "succeeded", "failed", "skipped"]


class PipelineNodeResponse(BaseModel):
    name: str = Field(..., description="Stable pipeline node name")
    dependencies: list[str] = Field(default_factory=list)
    status: PipelineNodeStatus
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    timestamps: dict[str, str | None] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)


class PipelineRunSummaryResponse(BaseModel):
    """Compact execution state used to locate and monitor collection runs."""

    run_id: str = Field(..., description="Stable pipeline run ID")
    pipeline_name: str = Field(..., description="Stable pipeline name")
    scope_type: str = Field(..., description="Execution scope kind")
    scope_id: str = Field(..., description="Execution scope ID")
    status: PipelineRunStatus = Field(..., description="Run lifecycle status")
    current_node: str | None = Field(default=None, description="Current phase or node")
    progress_percent: int = Field(default=0, ge=0, le=100)
    progress_detail: dict[str, Any] | None = Field(default=None)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    updated_at: str = Field(..., description="Last update timestamp")


class PipelineRunResponse(PipelineRunSummaryResponse):
    """Complete technical execution state for one pipeline invocation."""

    collection_id: str = Field(..., description="Owning Collection ID")
    mode: str = Field(..., description="Execution mode")
    input_fingerprint: str | None = Field(
        default=None,
        description="Identity of the input state consumed by this run",
    )
    nodes: dict[str, PipelineNodeResponse] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    resumed_from_run_id: str | None = Field(default=None)
    created_at: str = Field(..., description="Creation timestamp")
    started_at: str | None = Field(default=None, description="Start timestamp")
    finished_at: str | None = Field(default=None, description="Completion timestamp")


class PipelineRunListResponse(BaseModel):
    collection_id: str = Field(..., description="Owning Collection ID")
    count: int = Field(..., description="Number of returned runs")
    items: list[PipelineRunSummaryResponse] = Field(default_factory=list)


def pipeline_run_response(run: PipelineRun | PipelineRunSummary) -> dict[str, Any]:
    """Build the existing HTTP/SSE run shape from one domain run."""

    if isinstance(run, PipelineRunSummary):
        return _sanitize_preparation_errors(asdict(run))

    return _sanitize_preparation_errors(
        {
            **{key: value for key, value in asdict(run).items() if key != "timestamps"},
            "status": run.status.value,
            "nodes": {
                node.name: {
                    **asdict(node),
                    "dependencies": list(node.dependencies),
                    "status": node.status.value,
                    "errors": list(node.errors),
                    "warnings": list(node.warnings),
                    "stats": {
                        "duration_ms": node.stats.duration_ms,
                        "token_usage": (
                            asdict(node.stats.token_usage)
                            if node.stats.token_usage is not None
                            else None
                        ),
                        "model_usage": [asdict(item) for item in node.stats.model_usage],
                        "unreported_request_count": node.stats.unreported_request_count,
                        "prompt_versions": dict(node.stats.prompt_versions),
                    },
                    "timestamps": {
                        key: value
                        for key, value in asdict(node.timestamps).items()
                        if value is not None or key in ("started_at", "finished_at")
                    },
                }
                for node in run.nodes
            },
            "errors": list(run.errors),
            "warnings": list(run.warnings),
            "stats": {
                "duration_ms": run.stats.duration_ms,
                "token_usage": (
                    asdict(run.stats.token_usage)
                    if run.stats.token_usage is not None
                    else None
                ),
                "model_usage": [asdict(item) for item in run.stats.model_usage],
                "unreported_request_count": run.stats.unreported_request_count,
                "prompt_versions": dict(run.stats.prompt_versions),
            },
            "created_at": run.timestamps.created_at,
            "updated_at": run.timestamps.updated_at,
            "started_at": run.timestamps.started_at,
            "finished_at": run.timestamps.finished_at,
        }
    )


def _sanitize_preparation_errors(payload: dict[str, Any]) -> dict[str, Any]:
    if payload["pipeline_name"] != "document_preparation":
        return payload
    if payload["errors"]:
        payload["errors"] = [
            document_preparation_error_message(payload["current_node"])
        ]
    for name, node in payload.get("nodes", {}).items():
        if node["errors"]:
            node["errors"] = [document_preparation_error_message(name)]
    return payload


__all__ = [
    "pipeline_run_response",
    "PipelineNodeResponse",
    "PipelineNodeStatus",
    "PipelineRunListResponse",
    "PipelineRunResponse",
    "PipelineRunSummaryResponse",
    "PipelineRunStatus",
]
