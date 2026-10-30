"""Application service for observable technical pipeline execution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from repositories.pipeline_run_repository import (
    ExecutionStats,
    ExecutionTimestamps,
    PipelineNodeRun,
    PipelineNodeStatus,
    PipelineRun,
    PipelineRunRepository,
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


class PipelineRunService:
    """Own run admission and telemetry without owning scientific artifacts."""

    def __init__(self, repository: PipelineRunRepository) -> None:
        self.repository = repository

    async def create_run(
        self,
        collection_id: str,
        pipeline_name: str,
        *,
        scope_type: str,
        scope_id: str,
        mode: str = "standard",
        input_fingerprint: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._new_run(
            collection_id=collection_id,
            pipeline_name=pipeline_name,
            scope_type=scope_type,
            scope_id=scope_id,
            mode=mode,
            input_fingerprint=input_fingerprint,
            context=context,
        )
        run = await self.repository.add_run(run)
        return self._sanitize_preparation_errors(
            {
                **{
                    key: value
                    for key, value in asdict(run).items()
                    if key != "timestamps"
                },
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
                            "model_usage": [
                                asdict(item) for item in node.stats.model_usage
                            ],
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

    async def get_or_create_document_run(
        self,
        *,
        collection_id: str,
        document_id: str,
        pipeline_name: str,
        input_fingerprint: str,
        mode: str = "standard",
        context: Mapping[str, Any] | None = None,
        reuse_completed: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        if not document_id or not input_fingerprint:
            raise ValueError("document run requires document and input fingerprint")
        run, created = await self.repository.get_or_create_document_run(
            self._new_run(
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
        return (
            self._sanitize_preparation_errors(
                {
                    **{
                        key: value
                        for key, value in asdict(run).items()
                        if key != "timestamps"
                    },
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
                                "model_usage": [
                                    asdict(item) for item in node.stats.model_usage
                                ],
                                "unreported_request_count": node.stats.unreported_request_count,
                                "prompt_versions": dict(node.stats.prompt_versions),
                            },
                            "timestamps": {
                                key: value
                                for key, value in asdict(node.timestamps).items()
                                if value is not None
                                or key in ("started_at", "finished_at")
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
            ),
            created,
        )

    async def get_or_create_collection_run(
        self,
        *,
        collection_id: str,
        pipeline_name: str,
        input_fingerprint: str,
        mode: str = "standard",
        context: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if not input_fingerprint:
            raise ValueError("collection run requires an input fingerprint")
        run, created = await self.repository.get_or_create_collection_run(
            self._new_run(
                collection_id=collection_id,
                pipeline_name=pipeline_name,
                scope_type="collection",
                scope_id=collection_id,
                mode=mode,
                input_fingerprint=input_fingerprint,
                context=context,
            )
        )
        return (
            self._sanitize_preparation_errors(
                {
                    **{
                        key: value
                        for key, value in asdict(run).items()
                        if key != "timestamps"
                    },
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
                                "model_usage": [
                                    asdict(item) for item in node.stats.model_usage
                                ],
                                "unreported_request_count": node.stats.unreported_request_count,
                                "prompt_versions": dict(node.stats.prompt_versions),
                            },
                            "timestamps": {
                                key: value
                                for key, value in asdict(node.timestamps).items()
                                if value is not None
                                or key in ("started_at", "finished_at")
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
            ),
            created,
        )

    async def get_run(self, run_id: str) -> dict[str, Any]:
        run = await self.repository.read_run(run_id)
        if run is None:
            raise FileNotFoundError(f"pipeline run not found: {run_id}")
        return self._sanitize_preparation_errors(
            {
                **{
                    key: value
                    for key, value in asdict(run).items()
                    if key != "timestamps"
                },
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
                            "model_usage": [
                                asdict(item) for item in node.stats.model_usage
                            ],
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

    async def list_runs(
        self,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return [
            self._sanitize_preparation_errors(asdict(run))
            for run in await self.repository.list_runs(
                collection_id=collection_id,
                status=status,
                limit=limit,
                offset=offset,
            )
        ]

    async def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        current_node: str | None = None,
        progress_percent: int | None = None,
        progress_detail: Mapping[str, Any] | None = None,
        errors: Iterable[str] | None = None,
        warnings: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        if progress_percent is not None and not 0 <= progress_percent <= 100:
            raise ValueError("progress_percent must be between zero and 100")
        stored = await self.repository.read_run(run_id)
        if stored is None:
            raise FileNotFoundError(f"pipeline run not found: {run_id}")
        now = _now_iso()
        resolved_status = PipelineRunStatus(status or stored.status)
        updated = stored
        if resolved_status is PipelineRunStatus.RUNNING and stored.timestamps.started_at is None:
            updated = replace(
                updated,
                status=PipelineRunStatus.RUNNING,
                timestamps=replace(updated.timestamps, started_at=now, updated_at=now),
            )
        updated = self._transition_nodes(
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
                progress_detail
                if progress_detail is not None
                else stored.progress_detail
            ),
            errors=(
                tuple(errors)
                if errors is not None
                else updated.errors
            ),
            warnings=(
                tuple(warnings)
                if warnings is not None
                else updated.warnings
            ),
            timestamps=replace(updated.timestamps, updated_at=now),
        )
        if not await self.repository.update_run(updated):
            raise FileNotFoundError(f"pipeline run not found: {run_id}")
        return self._sanitize_preparation_errors(
            {
                **{
                    key: value
                    for key, value in asdict(updated).items()
                    if key != "timestamps"
                },
                "status": updated.status.value,
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
                            "model_usage": [
                                asdict(item) for item in node.stats.model_usage
                            ],
                            "unreported_request_count": node.stats.unreported_request_count,
                            "prompt_versions": dict(node.stats.prompt_versions),
                        },
                        "timestamps": {
                            key: value
                            for key, value in asdict(node.timestamps).items()
                            if value is not None or key in ("started_at", "finished_at")
                        },
                    }
                    for node in updated.nodes
                },
                "errors": list(updated.errors),
                "warnings": list(updated.warnings),
                "stats": {
                    "duration_ms": updated.stats.duration_ms,
                    "token_usage": (
                        asdict(updated.stats.token_usage)
                        if updated.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [asdict(item) for item in updated.stats.model_usage],
                    "unreported_request_count": updated.stats.unreported_request_count,
                    "prompt_versions": dict(updated.stats.prompt_versions),
                },
                "created_at": updated.timestamps.created_at,
                "updated_at": updated.timestamps.updated_at,
                "started_at": updated.timestamps.started_at,
                "finished_at": updated.timestamps.finished_at,
            }
        )

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        current_node: str | None = None,
        progress_percent: int = 100,
        progress_detail: Mapping[str, Any] | None = None,
        errors: Iterable[str] | None = None,
        warnings: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        resolved = PipelineRunStatus(status)
        if not resolved.is_terminal:
            raise ValueError("finished pipeline run requires a terminal status")
        return await self.update_run(
            run_id,
            status=resolved.value,
            current_node=current_node,
            progress_percent=progress_percent,
            progress_detail=progress_detail,
            errors=errors,
            warnings=warnings,
        )

    async def append_error(self, run_id: str, error: str) -> dict[str, Any]:
        stored = await self.repository.read_run(run_id)
        if stored is None:
            raise FileNotFoundError(f"pipeline run not found: {run_id}")
        return await self.update_run(run_id, errors=(*stored.errors, str(error)))

    def _new_run(
        self,
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
        for name, parents in dependencies.items():
            if name in parents:
                raise ValueError(f"pipeline node cannot depend on itself: {name}")
            if len(set(parents)) != len(parents):
                raise ValueError(f"pipeline node dependencies must be unique: {name}")
            unknown = set(parents) - dependencies.keys()
            if unknown:
                raise ValueError(
                    "pipeline node dependencies are not part of the run: "
                    + ", ".join(sorted(unknown))
                )
        remaining = {name: set(parents) for name, parents in dependencies.items()}
        while remaining:
            ready = {name for name, parents in remaining.items() if not parents}
            if not ready:
                raise ValueError("pipeline node dependencies contain a cycle")
            remaining = {
                name: parents - ready for name, parents in remaining.items()
                if name not in ready
            }
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

    @staticmethod
    def _transition_nodes(
        run: PipelineRun,
        *,
        current_node: str | None,
        status: PipelineRunStatus,
        errors: tuple[str, ...],
        now: str,
    ) -> PipelineRun:
        selected_name = PipelineRunService._semantic_node(run, current_node)
        if selected_name is None and not status.is_terminal:
            return run
        failed = status is PipelineRunStatus.FAILED or (
            run.pipeline_name == "document_preparation"
            and status is PipelineRunStatus.PARTIAL_SUCCESS
            and errors
        )
        if failed and selected_name is None:
            selected_name = next(
                (node.name for node in run.nodes if node.status is PipelineNodeStatus.RUNNING),
                next((node.name for node in run.nodes if node.status is PipelineNodeStatus.QUEUED), None),
            )
        nodes = []
        for node in run.nodes:
            if node.status.is_terminal:
                nodes.append(node)
                continue
            if not status.is_terminal:
                if node.name == selected_name and node.status is PipelineNodeStatus.QUEUED:
                    node = replace(
                        node, status=PipelineNodeStatus.RUNNING, errors=(),
                        timestamps=ExecutionTimestamps(started_at=now),
                    )
                elif node.name != selected_name and node.status is PipelineNodeStatus.RUNNING:
                    timestamps = replace(node.timestamps, finished_at=now)
                    node = replace(
                        node, status=PipelineNodeStatus.SUCCEEDED, warnings=(),
                        timestamps=timestamps, output_summary={},
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
                        node, status=PipelineNodeStatus.FAILED,
                        errors=(errors[0] if errors else "Pipeline execution failed.",),
                        timestamps=timestamps,
                        stats=replace(node.stats, duration_ms=timestamps.duration_ms()),
                    )
            elif status is PipelineRunStatus.PARTIAL_SUCCESS and node.status is PipelineNodeStatus.QUEUED:
                node = replace(
                    node, status=PipelineNodeStatus.SKIPPED,
                    timestamps=ExecutionTimestamps(finished_at=now),
                )
            else:
                timestamps = replace(
                    node.timestamps,
                    started_at=node.timestamps.started_at or now,
                    finished_at=now,
                )
                node = replace(
                    node, status=PipelineNodeStatus.SUCCEEDED, warnings=(),
                    timestamps=timestamps, output_summary={},
                    stats=ExecutionStats(duration_ms=timestamps.duration_ms()),
                )
            nodes.append(node)
        return replace(
            run,
            nodes=tuple(nodes),
            errors=tuple(f"{node.name}: {error}" for node in nodes for error in node.errors),
            warnings=tuple(f"{node.name}: {warning}" for node in nodes for warning in node.warnings),
            stats=ExecutionStats.aggregate(
                (node.stats for node in nodes), duration_ms=run.timestamps.duration_ms(),
            ),
        )

    @staticmethod
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

    @staticmethod
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


__all__ = ["PipelineRunService"]
