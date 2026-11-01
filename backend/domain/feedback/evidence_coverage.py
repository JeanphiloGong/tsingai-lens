"""A user-readable projection of what the analysis could inspect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

CoverageStatus = Literal["complete", "partial", "failed", "unknown"]


@dataclass(frozen=True)
class EvidenceCoverage:
    requested_scope: tuple[dict[str, Any], ...] = ()
    inspected_sources: tuple[dict[str, Any], ...] = ()
    omitted_candidates: tuple[dict[str, Any], ...] = ()
    claim_support: tuple[dict[str, Any], ...] = ()
    gaps: tuple[str, ...] = ()
    coverage_status: CoverageStatus = "unknown"
