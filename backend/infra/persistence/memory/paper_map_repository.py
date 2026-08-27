"""In-memory persistence for current document Paper Maps."""

from __future__ import annotations

from copy import deepcopy

from domain.core import PaperSkim


class MemoryPaperMapRepository:
    def __init__(self) -> None:
        self._maps: dict[tuple[str, str], PaperSkim] = {}

    async def replace(self, collection_id: str, paper_map: PaperSkim) -> None:
        self._maps[(collection_id, paper_map.document_id)] = deepcopy(paper_map)

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> PaperSkim | None:
        paper_map = self._maps.get((collection_id, document_id))
        return deepcopy(paper_map) if paper_map is not None else None

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[PaperSkim, ...]:
        selected = set(document_ids) if document_ids is not None else None
        return tuple(
            deepcopy(paper_map)
            for (owner_collection_id, document_id), paper_map in sorted(
                self._maps.items(), key=lambda item: item[0][1]
            )
            if owner_collection_id == collection_id
            and (selected is None or document_id in selected)
        )


__all__ = ["MemoryPaperMapRepository"]
