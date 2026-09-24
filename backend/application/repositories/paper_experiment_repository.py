"""Repository contract for immutable PaperExperiment revisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from domain.core.paper_experiment import PaperExperimentRevision


class PaperExperimentRevisionConflictError(ValueError):
    """Raised when an existing experiment version would be overwritten."""


@dataclass(frozen=True)
class StoredPaperExperimentRevision:
    revision_id: int
    revision: PaperExperimentRevision
    created_at: datetime
    created_by: str | None = None
    archived_at: datetime | None = None


class PaperExperimentRepository(Protocol):
    async def add_revision(
        self,
        revision: PaperExperimentRevision,
        *,
        created_by: str | None = None,
        created_at: datetime | None = None,
    ) -> StoredPaperExperimentRevision: ...

    async def read_revision(
        self,
        experiment_id: str,
        experiment_version: int,
    ) -> StoredPaperExperimentRevision | None: ...

    async def read_revision_by_id(
        self,
        revision_id: int,
    ) -> StoredPaperExperimentRevision | None: ...

    async def read_latest_revision(
        self,
        experiment_id: str,
    ) -> StoredPaperExperimentRevision | None: ...

    async def list_latest_for_document(
        self,
        document_id: str,
    ) -> tuple[StoredPaperExperimentRevision, ...]: ...


__all__ = [
    "PaperExperimentRepository",
    "PaperExperimentRevisionConflictError",
    "StoredPaperExperimentRevision",
]
