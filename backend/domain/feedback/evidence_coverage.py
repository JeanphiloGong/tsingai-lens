"""A user-readable projection of what the analysis could inspect."""

from __future__ import annotations

from dataclasses import dataclass, field
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

    def __post_init__(self) -> None:
        if self.coverage_status not in {"complete", "partial", "failed", "unknown"}:
            raise ValueError("invalid evidence coverage status")
        for name in (
            "requested_scope",
            "inspected_sources",
            "omitted_candidates",
            "claim_support",
        ):
            object.__setattr__(self, name, tuple(dict(item) for item in getattr(self, name)))
        object.__setattr__(self, "gaps", tuple(str(item) for item in self.gaps))

    def to_record(self) -> dict[str, Any]:
        return {
            "requested_scope": [dict(item) for item in self.requested_scope],
            "inspected_sources": [dict(item) for item in self.inspected_sources],
            "omitted_candidates": [dict(item) for item in self.omitted_candidates],
            "claim_support": [dict(item) for item in self.claim_support],
            "gaps": list(self.gaps),
            "coverage_status": self.coverage_status,
        }

    @classmethod
    def from_record(cls, payload: dict[str, Any] | None) -> "EvidenceCoverage":
        payload = payload or {}
        return cls(
            requested_scope=tuple(payload.get("requested_scope") or ()),
            inspected_sources=tuple(payload.get("inspected_sources") or ()),
            omitted_candidates=tuple(payload.get("omitted_candidates") or ()),
            claim_support=tuple(payload.get("claim_support") or ()),
            gaps=tuple(payload.get("gaps") or ()),
            coverage_status=payload.get("coverage_status") or "unknown",
        )
