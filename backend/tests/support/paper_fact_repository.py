from __future__ import annotations

from dataclasses import replace

from domain.core.document_profile import DocumentProfile
from domain.core.paper_fact import PaperFactSet


class MemoryPaperFactRepository:
    backend_name = "memory"

    def __init__(self, *, active_build_id: str = "build_test") -> None:
        self.active_build_id = active_build_id
        self._facts: dict[tuple[str, str], PaperFactSet] = {}

    def replace_document_profiles(
        self,
        collection_id: str,
        build_id: str,
        profiles: tuple[DocumentProfile, ...],
    ) -> None:
        key = (collection_id, build_id)
        self._facts[key] = replace(
            self._facts.get(key, PaperFactSet()),
            document_profiles=profiles,
        )

    def replace_paper_facts(
        self,
        collection_id: str,
        build_id: str,
        facts: PaperFactSet,
    ) -> None:
        key = (collection_id, build_id)
        self._facts[key] = replace(
            facts,
            document_profiles=self._facts.get(key, PaperFactSet()).document_profiles,
        )

    def read(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> PaperFactSet:
        selected_build_id = build_id or self.active_build_id
        return self._facts.get((collection_id, selected_build_id), PaperFactSet())

    def activate(self, build_id: str) -> None:
        self.active_build_id = build_id


__all__ = ["MemoryPaperFactRepository"]
