from __future__ import annotations

from dataclasses import replace

from domain.core import ObjectiveFactSet


class MemoryObjectiveRepository:
    backend_name = "memory"

    def __init__(self, *, active_build_id: str = "build_test") -> None:
        self.active_build_id = active_build_id
        self._facts: dict[tuple[str, str], ObjectiveFactSet] = {}
        self._lifecycles = {}

    @classmethod
    def from_facts(
        cls,
        collection_id: str,
        facts: ObjectiveFactSet,
        *,
        build_id: str = "build_test",
    ) -> "MemoryObjectiveRepository":
        repository = cls(active_build_id=build_id)
        repository.replace(collection_id, build_id, facts)
        return repository

    def replace(
        self,
        collection_id: str,
        build_id: str,
        facts: ObjectiveFactSet,
    ) -> None:
        self._facts[(collection_id, build_id)] = facts

    def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> ObjectiveFactSet:
        selected_build = build_id or self.active_build_id
        return self._facts.get((collection_id, selected_build), ObjectiveFactSet())

    def activate(self, build_id: str) -> None:
        self.active_build_id = build_id

    def list_objective_workspaces(self, collection_id: str):
        candidates = self.read(collection_id).research_objectives
        result = []
        seen = set()
        for candidate in candidates:
            lifecycle = self._lifecycles.get((collection_id, candidate.objective_id))
            result.append(
                lifecycle
                or replace(candidate, source_build_id=self.active_build_id)
            )
            seen.add(candidate.objective_id)
        result.extend(
            objective
            for (owned_collection_id, objective_id), objective in self._lifecycles.items()
            if owned_collection_id == collection_id and objective_id not in seen
        )
        return tuple(result)

    def read_objective_workspace(self, collection_id: str, objective_id: str):
        lifecycle = self._lifecycles.get((collection_id, objective_id))
        if lifecycle is not None:
            return lifecycle
        return next(
            (
                replace(objective, source_build_id=self.active_build_id)
                for objective in self.read(collection_id).research_objectives
                if objective.objective_id == objective_id
            ),
            None,
        )

    def confirm_objective(self, collection_id: str, objective_id: str):
        objective = self.read_objective_workspace(collection_id, objective_id)
        if objective is None:
            raise FileNotFoundError(objective_id)
        if objective.status == "candidate":
            objective = replace(objective, status="confirmed")
            self._lifecycles[(collection_id, objective_id)] = objective
        return objective

    def queue_objective_analysis(self, collection_id: str, objective_id: str):
        objective = self.read_objective_workspace(collection_id, objective_id)
        if objective is None:
            raise FileNotFoundError(objective_id)
        if objective.status == "candidate":
            raise ValueError("invalid objective status transition: candidate -> queued")
        if objective.status not in {"queued", "running"}:
            objective = replace(objective, status="queued", analysis_error=None)
            self._lifecycles[(collection_id, objective_id)] = objective
        return objective

    def claim_objective_analysis(self, collection_id: str, objective_id: str):
        objective = self.read_objective_workspace(collection_id, objective_id)
        if objective is None:
            raise FileNotFoundError(objective_id)
        if objective.status != "queued":
            return None
        objective = replace(objective, status="running")
        self._lifecycles[(collection_id, objective_id)] = objective
        return objective

    def update_objective_analysis_progress(
        self, collection_id: str, objective_id: str, analysis_progress
    ):
        objective = self.read_objective_workspace(collection_id, objective_id)
        objective = replace(objective, analysis_progress=dict(analysis_progress))
        self._lifecycles[(collection_id, objective_id)] = objective
        return objective

    def mark_objective_analysis_ready(self, collection_id: str, objective_id: str):
        objective = replace(
            self.read_objective_workspace(collection_id, objective_id),
            status="ready",
            analysis_error=None,
        )
        self._lifecycles[(collection_id, objective_id)] = objective
        return objective

    def mark_objective_analysis_failed(
        self, collection_id: str, objective_id: str, analysis_error: str
    ):
        objective = replace(
            self.read_objective_workspace(collection_id, objective_id),
            status="failed",
            analysis_error=analysis_error,
        )
        self._lifecycles[(collection_id, objective_id)] = objective
        return objective


__all__ = ["MemoryObjectiveRepository"]
