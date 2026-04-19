"""Document ingestion infrastructure adapters."""

from infra.source.ingestion.normalized_import import (
    NormalizedImportBatch,
    NormalizedImportDocument,
    NormalizedImportSourceMetadata,
    NormalizedImportTextUnit,
    normalize_upload,
)
from infra.source.ingestion.source_adapter import SourceAdapter, SourceAdapterRequest

__all__ = [
    "NormalizedImportBatch",
    "NormalizedImportDocument",
    "NormalizedImportSourceMetadata",
    "NormalizedImportTextUnit",
    "SourceAdapter",
    "SourceAdapterRequest",
    "normalize_upload",
]
