"""Repository contract for ObjectiveExperimentSelection records."""

from __future__ import annotations

from typing import Protocol

from domain.core.objective_experiment_selection import ObjectiveExperimentSelection


class ObjectiveExperimentSelectionRepository(Protocol):
    async def add_selection(
        self,
        collection_id: str,
        selection: ObjectiveExperimentSelection,
        *,
        revision_id: int,
    ) -> ObjectiveExperimentSelection: ...

    async def read_selection(
        self,
        collection_id: str,
        selection_id: str,
    ) -> ObjectiveExperimentSelection | None: ...

    async def list_selections(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[ObjectiveExperimentSelection, ...]: ...


__all__ = ["ObjectiveExperimentSelectionRepository"]
