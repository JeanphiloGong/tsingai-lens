"""Shared value objects for Source observations, Evidence, and Findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

SCIENTIFIC_RESULT_DIRECTIONS: Final[frozenset[str]] = frozenset(
    {
        "increase",
        "decrease",
        "improve",
        "worsen",
        "changed",
        "no_change",
        "mixed",
        "unknown",
    }
)
SCIENTIFIC_RESULT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "measured",
        "observed",
        "predicted",
        "simulated",
        "modeled",
        "unknown",
    }
)
SCIENTIFIC_CONTEXT_SCOPES: Final[frozenset[str]] = frozenset(
    {"experimental", "simulation", "background", "unknown"}
)

ScientificScalar = str | int | float | bool


@dataclass(frozen=True)
class ScientificAttribute:
    """One named material, sample, process, or test context value."""

    name: str
    value: ScientificScalar
    unit: str | None = None
    context_scope: str = "unknown"
    applies_to_outcomes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or self.value is None:
            raise ValueError("scientific attribute requires name and value")


@dataclass(frozen=True)
class ScientificVariable:
    """One factor label and its optional source-reported endpoints."""

    name: str
    baseline_value: ScientificScalar | None
    target_value: ScientificScalar | None
    unit: str | None = None


@dataclass(frozen=True)
class ScientificComparison:
    """Source-reported baseline/target roles and their comparison axes."""

    baseline_label: str
    target_label: str
    axis_names: tuple[str, ...]
    comparable: bool
    incomparability_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.baseline_label or not self.target_label:
            raise ValueError("scientific comparison requires both groups")
        if not self.axis_names:
            raise ValueError("scientific comparison requires axes")
        if not self.comparable and not self.incomparability_reasons:
            raise ValueError("incomparable scientific comparison requires reasons")
        if self.comparable and self.incomparability_reasons:
            raise ValueError(
                "comparable scientific comparison cannot have incomparability reasons"
            )


@dataclass(frozen=True)
class ScientificResult:
    """One source-reported outcome and its direction or scalar values."""

    outcome: str
    value: ScientificScalar | None
    unit: str | None
    direction: str
    result_text: str
    baseline_value: ScientificScalar | None = None
    target_value: ScientificScalar | None = None
    result_kind: str = "observed"


@dataclass(frozen=True)
class ScientificContext:
    """Material, sample, process, and test context for one scientific fact."""

    material: tuple[ScientificAttribute, ...] = ()
    sample: tuple[ScientificAttribute, ...] = ()
    process: tuple[ScientificAttribute, ...] = ()
    test: tuple[ScientificAttribute, ...] = ()


    @property
    def has_content(self) -> bool:
        return bool(self.material or self.sample or self.process or self.test)
