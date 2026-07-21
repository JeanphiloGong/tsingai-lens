from __future__ import annotations

from domain.core.comparison import ComparisonFactSet


class MemoryComparisonRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.facts_by_build: dict[tuple[str, str], ComparisonFactSet] = {}
        self.active_builds: dict[str, str] = {}

    def replace(
        self,
        collection_id: str,
        build_id: str,
        facts: ComparisonFactSet,
    ) -> None:
        self.facts_by_build[(collection_id, build_id)] = facts
        self.active_builds[collection_id] = build_id

    def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> ComparisonFactSet:
        resolved_build_id = build_id or self.active_builds.get(collection_id)
        if resolved_build_id is None:
            return ComparisonFactSet()
        return self.facts_by_build.get(
            (collection_id, resolved_build_id),
            ComparisonFactSet(),
        )


__all__ = ["MemoryComparisonRepository"]
