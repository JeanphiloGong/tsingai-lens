"""Repository contract for Findings backed by experiment selections."""

from __future__ import annotations

from typing import Protocol

from domain.core.finding import Finding


class ExperimentFindingRepository(Protocol):
    """Persist a Finding without copying its experiment facts."""

    async def add_finding(self, finding: Finding) -> Finding: ...

    async def read_finding(
        self,
        collection_id: str,
        finding_id: str,
    ) -> Finding | None: ...

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[Finding, ...]: ...


__all__ = ["ExperimentFindingRepository"]
