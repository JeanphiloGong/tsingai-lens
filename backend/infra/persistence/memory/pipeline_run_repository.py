"""In-memory pipeline-run persistence for tests and alternate hosts."""

from __future__ import annotations

from asyncio import Lock
from copy import deepcopy

from application.repositories.pipeline_run_repository import PipelineRunSummary

from domain.pipeline import PipelineRun


class MemoryPipelineRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, PipelineRun] = {}
        self._lock = Lock()

    async def add_run(self, run: PipelineRun) -> PipelineRun:
        async with self._lock:
            if run.run_id in self._runs:
                raise ValueError(f"duplicate pipeline run: {run.run_id}")
            self._runs[run.run_id] = deepcopy(run)
            return deepcopy(run)

    async def get_or_create_collection_run(
        self,
        run: PipelineRun,
    ) -> tuple[PipelineRun, bool]:
        if run.scope_type != "collection" or run.scope_id != run.collection_id:
            raise ValueError("collection run must use its collection as scope")
        return await self._get_or_create(run, reuse_completed=False)

    async def get_or_create_document_run(
        self,
        run: PipelineRun,
    ) -> tuple[PipelineRun, bool]:
        if run.scope_type != "document" or run.input_fingerprint is None:
            raise ValueError("document run requires document scope and input fingerprint")
        return await self._get_or_create(run, reuse_completed=True)

    async def _get_or_create(
        self,
        run: PipelineRun,
        *,
        reuse_completed: bool,
    ) -> tuple[PipelineRun, bool]:
        async with self._lock:
            matching = [
                stored
                for stored in self._runs.values()
                if stored.pipeline_name == run.pipeline_name
                and stored.scope_type == run.scope_type
                and stored.scope_id == run.scope_id
                and stored.status.value in {"queued", "running"}
            ]
            if matching:
                latest = max(
                    matching,
                    key=lambda item: (
                        item.timestamps.updated_at
                        or item.timestamps.created_at
                        or "",
                        item.run_id,
                    ),
                )
                return deepcopy(latest), False
            if reuse_completed:
                completed = [
                    stored
                    for stored in self._runs.values()
                    if stored.pipeline_name == run.pipeline_name
                    and stored.scope_type == run.scope_type
                    and stored.scope_id == run.scope_id
                    and stored.input_fingerprint == run.input_fingerprint
                    and stored.status.value in {"completed", "partial_success"}
                ]
                if completed:
                    latest = max(
                        completed,
                        key=lambda item: (item.timestamps.finished_at or "", item.run_id),
                    )
                    return deepcopy(latest), False
            self._runs[run.run_id] = deepcopy(run)
            return deepcopy(run), True

    async def read_run(self, run_id: str) -> PipelineRun | None:
        async with self._lock:
            run = self._runs.get(run_id)
            return deepcopy(run) if run is not None else None

    async def list_runs(
        self,
        *,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[PipelineRunSummary, ...]:
        async with self._lock:
            runs = [
                run
                for run in self._runs.values()
                if (collection_id is None or run.collection_id == collection_id)
                and (status is None or run.status.value == status)
            ]
            runs.sort(
                key=lambda item: (
                    item.timestamps.updated_at
                    or item.timestamps.finished_at
                    or item.timestamps.created_at
                    or "",
                    item.run_id,
                ),
                reverse=True,
            )
            selected = runs[offset : offset + limit if limit is not None else None]
            return tuple(
                PipelineRunSummary(
                    run_id=run.run_id,
                    collection_id=run.collection_id,
                    pipeline_name=run.pipeline_name,
                    scope_type=run.scope_type,
                    scope_id=run.scope_id,
                    status=run.status.value,
                    current_node=run.current_node,
                    progress_percent=run.progress_percent,
                    progress_detail=(
                        deepcopy(dict(run.progress_detail))
                        if run.progress_detail is not None
                        else None
                    ),
                    errors=list(run.errors),
                    warnings=list(run.warnings),
                    updated_at=run.timestamps.updated_at,
                )
                for run in selected
            )

    async def update_run(self, run: PipelineRun) -> bool:
        async with self._lock:
            if run.run_id not in self._runs:
                return False
            self._runs[run.run_id] = deepcopy(run)
            return True


__all__ = ["MemoryPipelineRunRepository"]
