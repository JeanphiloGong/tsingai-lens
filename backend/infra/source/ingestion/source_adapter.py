from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from infra.source.ingestion.normalized_import import NormalizedImportBatch


@dataclass(frozen=True)
class SourceAdapterRequest:
    """Collection-builder request passed to source adapters before Core import."""

    collection_id: str
    raw_locator: str
    goal_context: dict[str, Any] | None = None
    max_documents: int | None = None
    constraints: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    """Adapter contract for search/crawler/connector style source channels."""

    channel: str
    adapter_name: str
    adapter_version: str | None

    def fetch(self, request: SourceAdapterRequest) -> NormalizedImportBatch: ...
