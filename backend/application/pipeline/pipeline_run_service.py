"""Application service for observable technical pipeline execution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from exceptions import ResourceNotFoundException
from repositories.collection_repository import CollectionRepo
from repositories.pipeline_run_repository import (
    ExecutionStats,
    ExecutionTimestamps,
    PipelineNodeRun,
    PipelineNodeStatus,
    PipelineRun,
    PipelineRunSummary,
    PipelineRunStatus,
)

_PIPELINE_NODES: dict[str, dict[str, tuple[str, ...]]] = {
    "document_preparation": {
        "source_parsing": (),
        "document_profile": ("source_parsing",),
    },
    "objective_discovery": {
        "paper_map": (),
        "objective_candidates": ("paper_map",),
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def document_preparation_error_message(stage: str | None) -> str:
    return {
        "dispatch_failed": "Document preparation could not be scheduled. Retry preparation.",
        "source_parsing": "Document parsing failed. Check the file and retry preparation.",
        "document_profile": "Paper classification failed. Parsed Sources are preserved; retry preparation.",
        "interrupted": "Document preparation was interrupted by a backend restart. Retry preparation.",
    }.get(stage, "Document preparation failed. Retry preparation.")


from repositories.pipeline_run_repository import PipelineRunRepo


async def create_run(
    collection_id: str,
    pipeline_name: str,
    *,
    scope_type: str,
    scope_id: str,
    mode: str = "standard",
    input_fingerprint: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> PipelineRun:
    run = _new_run(
        collection_id=collection_id,
        pipeline_name=pipeline_name,
        scope_type=scope_type,
        scope_id=scope_id,
        mode=mode,
        input_fingerprint=input_fingerprint,
        context=context,
    )
    run = await PipelineRunRepo.add_run(run)
    return run


async def get_or_create_document_run(
    *,
    collection_id: str,
    document_id: str,
    pipeline_name: str,
    input_fingerprint: str,
    mode: str = "standard",
    context: Mapping[str, Any] | None = None,
    reuse_completed: bool = True,
) -> tuple[PipelineRun, bool]:
    if not document_id or not input_fingerprint:
        raise ValueError("document run requires document and input fingerprint")
    run, created = await PipelineRunRepo.get_or_create_document_run(
        _new_run(
            collection_id=collection_id,
            pipeline_name=pipeline_name,
            scope_type="document",
            scope_id=document_id,
            mode=mode,
            input_fingerprint=input_fingerprint,
            context=context,
        ),
        reuse_completed=reuse_completed,
    )
    return run, created


async def get_or_create_collection_run(
    *,
    collection_id: str,
    pipeline_name: str,
    input_fingerprint: str,
    mode: str = "standard",
    context: Mapping[str, Any] | None = None,
) -> tuple[PipelineRun, bool]:
    if not input_fingerprint:
        raise ValueError("collection run requires an input fingerprint")
    run, created = await PipelineRunRepo.get_or_create_collection_run(
        _new_run(
            collection_id=collection_id,
            pipeline_name=pipeline_name,
            scope_type="collection",
            scope_id=collection_id,
            mode=mode,
            input_fingerprint=input_fingerprint,
            context=context,
        )
    )
    return run, created


async def get_run(run_id: str, *, user_id: str) -> PipelineRun:
    run = await PipelineRunRepo.read_run(run_id)
    if run is None:
        raise ResourceNotFoundException(
            "Pipeline run not found.",
            data={"code": "pipeline_run_not_found", "run_id": run_id},
        )
    if not await CollectionRepo.collection_belongs_to_user(run.collection_id, user_id):
        raise ResourceNotFoundException(
            "Pipeline run not found.",
            data={"code": "pipeline_run_not_found", "run_id": run_id},
        )
    return run


async def list_runs(
    collection_id: str,
    status: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    *,
    user_id: str,
) -> list[PipelineRunSummary]:
    if not await CollectionRepo.collection_belongs_to_user(collection_id, user_id):
        raise ResourceNotFoundException(
            "Collection not found.",
            data={"code": "collection_not_found", "collection_id": collection_id},
        )
    return await PipelineRunRepo.list_runs(
        collection_id=collection_id, status=status, limit=limit, offset=offset,
    )


async def list_interrupted_runs() -> list[PipelineRunSummary]:
    """Read durable queued/running work before startup recovery admits requests."""
    return [
        run
        for status in ("queued", "running")
        for run in await PipelineRunRepo.list_runs(status=status)
    ]


async def update_run(
    run_id: str,
    *,
    status: str | None = None,
    current_node: str | None = None,
    progress_percent: int | None = None,
    progress_detail: Mapping[str, Any] | None = None,
    errors: Iterable[str] | None = None,
    warnings: Iterable[str] | None = None,
) -> PipelineRun:
    if progress_percent is not None and not 0 <= progress_percent <= 100:
        raise ValueError("progress_percent must be between zero and 100")
    stored = await PipelineRunRepo.read_run(run_id)
    if stored is None:
        raise ResourceNotFoundException(
            "Pipeline run not found.",
            data={"code": "pipeline_run_not_found", "run_id": run_id},
        )
    now = _now_iso()
    resolved_status = PipelineRunStatus(status or stored.status)
    updated = stored
    if (
        resolved_status is PipelineRunStatus.RUNNING
        and stored.timestamps.started_at is None
    ):
        updated = replace(
            updated,
            status=PipelineRunStatus.RUNNING,
            timestamps=replace(updated.timestamps, started_at=now, updated_at=now),
        )
    updated = _transition_nodes(
        updated,
        current_node=current_node or stored.current_node,
        status=resolved_status,
        errors=tuple(errors or ()),
        now=now,
    )
    if resolved_status.is_terminal:
        timestamps = replace(updated.timestamps, finished_at=now, updated_at=now)
        updated = replace(
            updated,
            status=resolved_status,
            timestamps=timestamps,
            stats=replace(updated.stats, duration_ms=timestamps.duration_ms()),
        )
    else:
        updated = replace(updated, status=resolved_status)
    updated = replace(
        updated,
        current_node=current_node if current_node is not None else stored.current_node,
        progress_percent=(
            progress_percent
            if progress_percent is not None
            else stored.progress_percent
        ),
        progress_detail=(
            progress_detail if progress_detail is not None else stored.progress_detail
        ),
        errors=(tuple(errors) if errors is not None else updated.errors),
        warnings=(tuple(warnings) if warnings is not None else updated.warnings),
        timestamps=replace(updated.timestamps, updated_at=now),
    )
    if not await PipelineRunRepo.update_run(updated):
        raise ResourceNotFoundException(
            "Pipeline run not found.",
            data={"code": "pipeline_run_not_found", "run_id": run_id},
        )
    return updated


async def finish_run(
    run_id: str,
    *,
    status: str,
    current_node: str | None = None,
    progress_percent: int = 100,
    progress_detail: Mapping[str, Any] | None = None,
    errors: Iterable[str] | None = None,
    warnings: Iterable[str] | None = None,
) -> PipelineRun:
    resolved = PipelineRunStatus(status)
    if not resolved.is_terminal:
        raise ValueError("finished pipeline run requires a terminal status")
    return await update_run(
        run_id,
        status=resolved.value,
        current_node=current_node,
        progress_percent=progress_percent,
        progress_detail=progress_detail,
        errors=errors,
        warnings=warnings,
    )


async def append_error(run_id: str, error: str) -> PipelineRun:
    stored = await PipelineRunRepo.read_run(run_id)
    if stored is None:
        raise ResourceNotFoundException(
            "Pipeline run not found.",
            data={"code": "pipeline_run_not_found", "run_id": run_id},
        )
    return await update_run(run_id, errors=(*stored.errors, str(error)))


def _new_run(
    *,
    collection_id: str,
    pipeline_name: str,
    scope_type: str,
    scope_id: str,
    mode: str,
    input_fingerprint: str | None,
    context: Mapping[str, Any] | None,
) -> PipelineRun:
    now = _now_iso()
    dependencies = _PIPELINE_NODES.get(pipeline_name, {})
    if not all((pipeline_name, mode, collection_id, scope_type, scope_id)):
        raise ValueError("pipeline run identity is required")
    return PipelineRun(
        pipeline_name=pipeline_name,
        mode=mode,
        run_id=f"run_{uuid4().hex[:12]}",
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
        status=PipelineRunStatus.QUEUED,
        nodes=tuple(
            PipelineNodeRun(name=name, dependencies=tuple(parents))
            for name, parents in dependencies.items()
        ),
        errors=(),
        warnings=(),
        stats=ExecutionStats(),
        timestamps=ExecutionTimestamps(created_at=now, updated_at=now),
        input_fingerprint=input_fingerprint,
        context=context or {},
        current_node="queued",
    )


def _transition_nodes(
    run: PipelineRun,
    *,
    current_node: str | None,
    status: PipelineRunStatus,
    errors: tuple[str, ...],
    now: str,
) -> PipelineRun:
    selected_name = _semantic_node(run, current_node)
    if selected_name is None and not status.is_terminal:
        return run
    failed = status is PipelineRunStatus.FAILED or (
        run.pipeline_name == "document_preparation"
        and status is PipelineRunStatus.PARTIAL_SUCCESS
        and errors
    )
    if failed and selected_name is None:
        selected_name = next(
            (
                node.name
                for node in run.nodes
                if node.status is PipelineNodeStatus.RUNNING
            ),
            next(
                (
                    node.name
                    for node in run.nodes
                    if node.status is PipelineNodeStatus.QUEUED
                ),
                None,
            ),
        )
    nodes = []
    for node in run.nodes:
        if node.status.is_terminal:
            nodes.append(node)
            continue
        if not status.is_terminal:
            if node.name == selected_name and node.status is PipelineNodeStatus.QUEUED:
                node = replace(
                    node,
                    status=PipelineNodeStatus.RUNNING,
                    errors=(),
                    timestamps=ExecutionTimestamps(started_at=now),
                )
            elif (
                node.name != selected_name and node.status is PipelineNodeStatus.RUNNING
            ):
                timestamps = replace(node.timestamps, finished_at=now)
                node = replace(
                    node,
                    status=PipelineNodeStatus.SUCCEEDED,
                    warnings=(),
                    timestamps=timestamps,
                    output_summary={},
                    stats=ExecutionStats(duration_ms=timestamps.duration_ms()),
                )
        elif failed:
            if node.name == selected_name:
                timestamps = replace(
                    node.timestamps,
                    started_at=node.timestamps.started_at or now,
                    finished_at=now,
                )
                node = replace(
                    node,
                    status=PipelineNodeStatus.FAILED,
                    errors=(errors[0] if errors else "Pipeline execution failed.",),
                    timestamps=timestamps,
                    stats=replace(node.stats, duration_ms=timestamps.duration_ms()),
                )
        elif (
            status is PipelineRunStatus.PARTIAL_SUCCESS
            and node.status is PipelineNodeStatus.QUEUED
        ):
            node = replace(
                node,
                status=PipelineNodeStatus.SKIPPED,
                timestamps=ExecutionTimestamps(finished_at=now),
            )
        else:
            timestamps = replace(
                node.timestamps,
                started_at=node.timestamps.started_at or now,
                finished_at=now,
            )
            node = replace(
                node,
                status=PipelineNodeStatus.SUCCEEDED,
                warnings=(),
                timestamps=timestamps,
                output_summary={},
                stats=ExecutionStats(duration_ms=timestamps.duration_ms()),
            )
        nodes.append(node)
    return replace(
        run,
        nodes=tuple(nodes),
        errors=tuple(
            f"{node.name}: {error}" for node in nodes for error in node.errors
        ),
        warnings=tuple(
            f"{node.name}: {warning}" for node in nodes for warning in node.warnings
        ),
        stats=ExecutionStats.aggregate(
            (node.stats for node in nodes),
            duration_ms=run.timestamps.duration_ms(),
        ),
    )


def _semantic_node(run: PipelineRun, phase: str | None) -> str | None:
    if not phase:
        return None
    if any(node.name == phase for node in run.nodes):
        return phase
    if run.pipeline_name == "objective_discovery":
        if phase.startswith("paper_"):
            return "paper_map"
        if phase.startswith("objective_discovery"):
            return "objective_candidates"
    return None


__all__ = [
    "create_run",
    "get_or_create_document_run",
    "get_or_create_collection_run",
    "get_run",
    "list_runs",
    "update_run",
    "finish_run",
    "append_error",
]
