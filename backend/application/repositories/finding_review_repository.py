from __future__ import annotations

from typing import Protocol

from domain.evaluation import FindingCuration, FindingFeedback


class FindingReviewRepository(Protocol):
    backend_name: str

    async def upsert_feedback(
        self,
        feedback: FindingFeedback,
    ) -> FindingFeedback: ...

    async def list_feedback(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingFeedback, ...]: ...

    async def upsert_curation(
        self,
        curation: FindingCuration,
    ) -> FindingCuration: ...

    async def list_curations(
        self,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingCuration, ...]: ...
