"""Objective-scoped selection of reusable PaperExperiment content."""

from __future__ import annotations

from dataclasses import dataclass


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
        if not all((self.selection_id, self.objective_id, self.experiment_id, self.outcome)):
            raise ValueError("selection requires identity and outcome")
        if self.analysis_version < 1 or self.experiment_version < 1:
            raise ValueError("selection versions must be positive")
        if not self.measurement_keys and not self.comparison_keys:
            raise ValueError("selection must choose measurements or comparisons")


__all__ = ["ObjectiveExperimentSelection"]
