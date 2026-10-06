"""Persistence contract for task-dataset export previews and releases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.feedback.dataset_export import (
    DatasetExport,
    ExportMember,
    ExportPreview,
)


@dataclass(frozen=True)
class DatasetExportDraft:
    dataset_id: str
    preview_id: str
    preview_digest: str
    member_digest: str
    rows: tuple[dict, ...]
    provenance: tuple[dict, ...]
    members: tuple[ExportMember, ...]
    content_digest: str
    provenance_digest: str
    manifest_digest: str
    manifest: dict
    created_by: str
    idempotency_key: str
    created_at: str


@dataclass(frozen=True)
class DatasetExportSummary:
    export_id: str
    dataset_id: str
    export_no: int
    schema_version: str
    row_count: int
    content_digest: str
    provenance_digest: str
    manifest_digest: str
    created_at: str


class DatasetExportConflict(ValueError):
    """The preview or confirmed member set changed before publication."""


class DatasetExportIdempotencyConflict(ValueError):
    """An idempotency key was reused with a different publication request."""


class FeedbackDatasetExportRepository(Protocol):
    async def save_preview(self, preview: ExportPreview) -> ExportPreview: ...

    async def read_preview(self, preview_id: str) -> ExportPreview | None: ...

    async def list_exports(
        self, *, dataset_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[DatasetExportSummary, ...]: ...

    async def publish_if_current(
        self,
        *,
        draft: DatasetExportDraft,
    ) -> DatasetExport: ...

    async def read_export(self, export_id: str) -> DatasetExport | None: ...


__all__ = [
    "DatasetExportConflict",
    "DatasetExportDraft",
    "DatasetExportIdempotencyConflict",
    "DatasetExportSummary",
    "FeedbackDatasetExportRepository",
]
