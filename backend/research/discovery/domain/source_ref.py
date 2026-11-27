from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaperResearchSourceRef:
    """Stable Source locator supporting a preliminary paper-map judgment."""

    source_kind: str
    source_ref: str
