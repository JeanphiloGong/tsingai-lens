"""Application service for observable technical pipeline execution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from domain.pipeline import (
    ExecutionTimestamps,
    PipelineNodeRun,
    PipelineNodeStatus,
    PipelineRun,
    PipelineRunStatus,
)
from domain.ports import PipelineRunRepository


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
        return self._project(await self.repository.add_run(run))

    async def get_or_create_document_run(
        self,
        *,
        collection_id: str,
        document_id: str,
        pipeline_name: str,
        input_fingerprint: str,
        mode: str = "standard",
        context: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if not str(document_id).strip() or not str(input_fingerprint).strip():
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
            )
        )
        return self._project(run), created

    async def get_or_create_collection_run(
        self,
        *,
        collection_id: str,
        pipeline_name: str,
        input_fingerprint: str,
        mode: str = "standard",
        context: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if not str(input_fingerprint).strip():
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
        return self._project(run), created

    async def get_run(self, run_id: str) -> dict[str, Any]:
        run = await self.repository.read_run(run_id)
        if run is None:
            raise FileNotFoundError(f"pipeline run not found: {run_id}")
        return self._project(run)

    async def list_runs(
        self,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return [
            self._project(run)
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
        stored = await self.repository.read_run(run_id)
        if stored is None:
            raise FileNotFoundError(f"pipeline run not found: {run_id}")
        now = _now_iso()
        resolved_status = PipelineRunStatus(status or stored.status)
        updated = stored
        if resolved_status is PipelineRunStatus.RUNNING and stored.timestamps.started_at is None:
            updated = updated.start(now)
        updated = self._transition_nodes(
            updated,
            current_node=current_node or stored.current_node,
            status=resolved_status,
            errors=tuple(str(error) for error in errors or ()),
            now=now,
        )
        if resolved_status.is_terminal:
            updated = updated.finish(resolved_status, now)
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
                dict(progress_detail)
                if progress_detail is not None
                else stored.progress_detail
            ),
            errors=(
                tuple(str(error) for error in errors)
                if errors is not None
                else updated.errors
            ),
            warnings=(
                tuple(str(warning) for warning in warnings)
                if warnings is not None
                else updated.warnings
            ),
            timestamps=replace(updated.timestamps, updated_at=now),
        )
        if not await self.repository.update_run(updated):
            raise FileNotFoundError(f"pipeline run not found: {run_id}")
        return self._project(updated)

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
        return replace(
            PipelineRun.create(
                pipeline_name=str(pipeline_name),
                mode=str(mode).strip() or "standard",
                run_id=f"run_{uuid4().hex[:12]}",
                collection_id=str(collection_id),
                scope_type=str(scope_type),
                scope_id=str(scope_id),
                input_fingerprint=input_fingerprint,
                context=context,
                node_dependencies=_PIPELINE_NODES.get(str(pipeline_name), {}),
                created_at=now,
            ),
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
        updated = run
        if selected_name is not None and not status.is_terminal:
            nodes = []
            for node in updated.nodes:
                if node.status is PipelineNodeStatus.RUNNING and node.name != selected_name:
                    node = node.succeed(now)
                if node.name == selected_name and node.status is PipelineNodeStatus.QUEUED:
                    node = node.start(now)
                nodes.append(node)
            for node in nodes:
                updated = updated.with_node(node)
        if not status.is_terminal:
            return updated

        if status is PipelineRunStatus.FAILED:
            failed_name = selected_name or next(
                (
                    node.name
                    for node in updated.nodes
                    if node.status is PipelineNodeStatus.RUNNING
                ),
                None,
            )
            if failed_name is None:
                failed_name = next(
                    (
                        node.name
                        for node in updated.nodes
                        if node.status is PipelineNodeStatus.QUEUED
                    ),
                    None,
                )
            if failed_name is not None:
                node = updated.node(failed_name)
                if node.status is PipelineNodeStatus.QUEUED:
                    node = node.start(now)
                if not node.status.is_terminal:
                    node = node.fail(errors[0] if errors else "Pipeline execution failed.", now)
                updated = updated.with_node(node)
            return updated

        for node in updated.nodes:
            if node.status.is_terminal:
                continue
            if status is PipelineRunStatus.PARTIAL_SUCCESS and node.status is PipelineNodeStatus.QUEUED:
                updated = updated.with_node(node.skip(finished_at=now))
                continue
            if node.status is PipelineNodeStatus.QUEUED:
                node = node.start(now)
            updated = updated.with_node(node.succeed(now))
        return updated

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
    def _project(run: PipelineRun) -> dict[str, Any]:
        payload = run.to_record()
        timestamps = payload.pop("timestamps")
        return {
            **payload,
            "created_at": timestamps.get("created_at"),
            "updated_at": timestamps.get("updated_at"),
            "started_at": timestamps.get("started_at"),
            "finished_at": timestamps.get("finished_at"),
        }


__all__ = ["PipelineRunService"]
