from __future__ import annotations

from typing import Protocol

from domain.core.research_objective import PaperResearchMap


class PaperMapRepository(Protocol):
    async def replace(self, collection_id: str, paper_map: PaperResearchMap) -> None: ...

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> PaperResearchMap | None: ...

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[PaperResearchMap, ...]: ...
