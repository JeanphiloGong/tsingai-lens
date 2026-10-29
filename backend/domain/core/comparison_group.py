"""Optional cross-paper comparison grouping for one analysis snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


@dataclass(frozen=True)
class ComparisonGroupMember:
    selection_id: str
    role: Literal["included", "context", "excluded"]
    comparability: Literal["comparable", "conditional", "non_comparable", "unknown"]
    reason: str

    def __post_init__(self) -> None:
        if self.role == "included" and self.comparability == "non_comparable":
            raise ValueError("non-comparable member cannot be included")


@dataclass(frozen=True)
class ComparisonGroup:
    group_id: str
    objective_id: str
    analysis_version: int
    outcome: str
    comparison_target: Literal["measurement", "within_paper_comparison"]
    comparison_basis: tuple[str, ...]
    members: tuple[ComparisonGroupMember, ...]
    normalizations: tuple[Mapping[str, Any], ...] = ()
    status: Literal["comparable", "conditional", "insufficient"] = "insufficient"
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.group_id.strip() or not self.objective_id.strip() or not self.outcome.strip():
            raise ValueError("comparison group requires identity and outcome")
        if self.analysis_version < 1:
            raise ValueError("comparison group analysis_version must be positive")
        if not self.comparison_basis:
            raise ValueError("comparison group requires a comparison basis")
        ids = [item.selection_id for item in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("comparison group members must be unique")
        if self.status == "comparable" and any(
            item.role == "included" and item.comparability != "comparable"
            for item in self.members
        ):
            raise ValueError("comparable group requires comparable included members")


__all__ = [
    "ComparisonGroup",
    "ComparisonGroupMember",
]
