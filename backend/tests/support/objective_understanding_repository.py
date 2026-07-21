from __future__ import annotations

from domain.core import ResearchUnderstanding


class InMemoryObjectiveUnderstandingRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], ResearchUnderstanding] = {}

    def upsert_objective_understanding(
        self,
        collection_id: str,
        objective_id: str,
        understanding: ResearchUnderstanding,
    ) -> None:
        self.items[(collection_id, objective_id)] = understanding

    def read_objective_understanding(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchUnderstanding | None:
        return self.items.get((collection_id, objective_id))

    def list_objective_understandings(
        self,
        collection_id: str,
    ) -> tuple[ResearchUnderstanding, ...]:
        return tuple(
            understanding
            for (stored_collection_id, _objective_id), understanding in self.items.items()
            if stored_collection_id == collection_id
        )
