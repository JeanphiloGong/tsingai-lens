from __future__ import annotations

from domain.core import ObjectiveFactSet


class MemoryObjectiveRepository:
    backend_name = "memory"

    def __init__(self, *, active_build_id: str = "build_test") -> None:
        self.active_build_id = active_build_id
        self._facts: dict[tuple[str, str], ObjectiveFactSet] = {}

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


__all__ = ["MemoryObjectiveRepository"]
