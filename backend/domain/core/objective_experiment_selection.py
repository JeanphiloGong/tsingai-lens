"""Objective-scoped selection of reusable PaperExperiment content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _terms(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set)):
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = str(value).strip()
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            result.append(term)
    return tuple(result)


@dataclass(frozen=True)
class ObjectiveExperimentSelection:
    """A fixed, explicit slice of one experiment used by one analysis."""

    selection_id: str
    objective_id: str
    analysis_version: int
    experiment_id: str
    experiment_version: int
    outcome: str
    measurement_keys: tuple[str, ...] = ()
    comparison_keys: tuple[str, ...] = ()
    missing_context: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "selection_id",
            "objective_id",
            "experiment_id",
            "outcome",
        ):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"selection requires {field_name}")
        if self.analysis_version < 1 or self.experiment_version < 1:
            raise ValueError("selection versions must be positive")
        object.__setattr__(self, "measurement_keys", _terms(self.measurement_keys))
        object.__setattr__(self, "comparison_keys", _terms(self.comparison_keys))
        object.__setattr__(self, "missing_context", _terms(self.missing_context))
        object.__setattr__(self, "reasons", _terms(self.reasons))
        if not self.measurement_keys and not self.comparison_keys:
            raise ValueError("selection must choose measurements or comparisons")


__all__ = ["ObjectiveExperimentSelection"]
