from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from domain.pipeline import PipelineRun


@dataclass(frozen=True)
class PipelineRunSummary:
    run_id: str
    collection_id: str
    pipeline_name: str
    scope_type: str
    scope_id: str
    status: str
    current_node: str | None
    progress_percent: int
    progress_detail: dict[str, Any] | None
    errors: list[str]
    warnings: list[str]
    updated_at: str


class PipelineRunRepository(Protocol):
    async def add_run(self, run: PipelineRun) -> PipelineRun: ...

    async def get_or_create_collection_run(
        self,
        run: PipelineRun,
    ) -> tuple[PipelineRun, bool]: ...

    async def get_or_create_document_run(
        self,
        run: PipelineRun,
    ) -> tuple[PipelineRun, bool]: ...

    async def read_run(self, run_id: str) -> PipelineRun | None: ...

    async def list_runs(
        self,
        *,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[PipelineRunSummary, ...]: ...

    async def update_run(self, run: PipelineRun) -> bool: ...
