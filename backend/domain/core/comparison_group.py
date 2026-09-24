"""Optional cross-paper comparison grouping for one analysis snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


GROUP_TARGETS = frozenset({"measurement", "within_paper_comparison"})
GROUP_STATUSES = frozenset({"comparable", "conditional", "insufficient"})
MEMBER_ROLES = frozenset({"included", "context", "excluded"})
MEMBER_COMPARABILITY = frozenset(
    {"comparable", "conditional", "non_comparable", "unknown"}
)


def _terms(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return tuple(result)


@dataclass(frozen=True)
class ComparisonGroupMember:
    selection_id: str
    role: str
    comparability: str
    reason: str

    def __post_init__(self) -> None:
        if not self.selection_id.strip() or not self.reason.strip():
            raise ValueError("comparison group member requires selection and reason")
        if self.role not in MEMBER_ROLES:
            raise ValueError(f"unsupported comparison member role: {self.role}")
        if self.comparability not in MEMBER_COMPARABILITY:
            raise ValueError(
                f"unsupported comparison member comparability: {self.comparability}"
            )
        if self.role == "included" and self.comparability == "non_comparable":
            raise ValueError("non-comparable member cannot be included")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ComparisonGroupMember":
        return cls(
            selection_id=str(payload.get("selection_id") or "").strip(),
            role=str(payload.get("role") or "").strip(),
            comparability=str(payload.get("comparability") or "unknown").strip(),
            reason=str(payload.get("reason") or "").strip(),
        )

    def to_record(self) -> dict[str, str]:
        return {
            "selection_id": self.selection_id,
            "role": self.role,
            "comparability": self.comparability,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ComparisonGroup:
    group_id: str
    objective_id: str
    analysis_version: int
    outcome: str
    comparison_target: str
    comparison_basis: tuple[str, ...]
    members: tuple[ComparisonGroupMember, ...]
    normalizations: tuple[Mapping[str, Any], ...] = ()
    status: str = "insufficient"
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.group_id.strip() or not self.objective_id.strip() or not self.outcome.strip():
            raise ValueError("comparison group requires identity and outcome")
        if self.analysis_version < 1:
            raise ValueError("comparison group analysis_version must be positive")
        if self.comparison_target not in GROUP_TARGETS:
            raise ValueError(f"unsupported comparison target: {self.comparison_target}")
        if self.status not in GROUP_STATUSES:
            raise ValueError(f"unsupported comparison group status: {self.status}")
        if not self.comparison_basis:
            raise ValueError("comparison group requires a comparison basis")
        if not self.members:
            raise ValueError("comparison group requires members")
        ids = [item.selection_id for item in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("comparison group members must be unique")
        if self.status == "comparable" and any(
            item.role == "included" and item.comparability != "comparable"
            for item in self.members
        ):
            raise ValueError("comparable group requires comparable included members")
        object.__setattr__(
            self,
            "normalizations",
            tuple(dict(item) for item in self.normalizations if isinstance(item, Mapping)),
        )
        object.__setattr__(self, "limitations", _terms(self.limitations))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ComparisonGroup":
        return cls(
            group_id=str(payload.get("group_id") or "").strip(),
            objective_id=str(payload.get("objective_id") or "").strip(),
            analysis_version=int(payload.get("analysis_version") or 0),
            outcome=str(payload.get("outcome") or "").strip(),
            comparison_target=str(payload.get("comparison_target") or "").strip(),
            comparison_basis=_terms(payload.get("comparison_basis")),
            members=tuple(
                ComparisonGroupMember.from_mapping(item)
                for item in payload.get("members") or ()
                if isinstance(item, Mapping)
            ),
            normalizations=tuple(
                dict(item)
                for item in payload.get("normalizations") or ()
                if isinstance(item, Mapping)
            ),
            status=str(payload.get("status") or "insufficient").strip(),
            limitations=_terms(payload.get("limitations")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "objective_id": self.objective_id,
            "analysis_version": self.analysis_version,
            "outcome": self.outcome,
            "comparison_target": self.comparison_target,
            "comparison_basis": list(self.comparison_basis),
            "members": [item.to_record() for item in self.members],
            "normalizations": [dict(item) for item in self.normalizations],
            "status": self.status,
            "limitations": list(self.limitations),
        }


__all__ = [
    "ComparisonGroup",
    "ComparisonGroupMember",
    "GROUP_STATUSES",
    "GROUP_TARGETS",
    "MEMBER_COMPARABILITY",
    "MEMBER_ROLES",
]
