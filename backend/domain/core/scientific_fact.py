"""Shared value objects for Source observations, Evidence, and Findings."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Final, Mapping


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
        if not _text(self.name) or _scientific_scalar(self.value) is None:
            raise ValueError("scientific attribute requires name and value")
        if self.context_scope not in SCIENTIFIC_CONTEXT_SCOPES:
            raise ValueError(
                f"unsupported scientific context scope: {self.context_scope}"
            )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ScientificAttribute":
        value = _scientific_scalar(payload.get("value"))
        return cls(
            name=_text(payload.get("name")) or "",
            value=value if value is not None else "",
            unit=_text(payload.get("unit")),
            context_scope=_choice(
                payload.get("context_scope"),
                SCIENTIFIC_CONTEXT_SCOPES,
                "unknown",
            ),
            applies_to_outcomes=_terms(payload.get("applies_to_outcomes")),
        )

    def to_record(self) -> dict[str, Any]:
        record = {"name": self.name, "value": self.value, "unit": self.unit}
        # The default is omitted so persisted Evidence retains its established
        # payload shape. Explicit scope changes how context may be compared.
        if self.context_scope != "unknown":
            record["context_scope"] = self.context_scope
        if self.applies_to_outcomes:
            record["applies_to_outcomes"] = list(self.applies_to_outcomes)
        return record


@dataclass(frozen=True)
class ScientificVariable:
    """One factor label and its optional source-reported endpoints."""

    name: str
    baseline_value: ScientificScalar | None
    target_value: ScientificScalar | None
    unit: str | None = None

    def __post_init__(self) -> None:
        if not _text(self.name):
            raise ValueError("scientific variable requires name")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ScientificVariable":
        return cls(
            name=_text(payload.get("name")) or "",
            baseline_value=_scientific_scalar(payload.get("baseline_value")),
            target_value=_scientific_scalar(payload.get("target_value")),
            unit=_text(payload.get("unit")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "baseline_value": self.baseline_value,
            "target_value": self.target_value,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class ScientificComparison:
    """Source-reported baseline/target roles and their comparison axes."""

    baseline_label: str
    target_label: str
    axis_names: tuple[str, ...]
    comparable: bool
    incomparability_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _text(self.baseline_label) or not _text(self.target_label):
            raise ValueError("scientific comparison requires both groups")
        if not self.axis_names:
            raise ValueError("scientific comparison requires axes")
        if not self.comparable and not self.incomparability_reasons:
            raise ValueError("incomparable scientific comparison requires reasons")
        if self.comparable and self.incomparability_reasons:
            raise ValueError(
                "comparable scientific comparison cannot have incomparability reasons"
            )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ScientificComparison":
        return cls(
            baseline_label=_text(payload.get("baseline_label")) or "",
            target_label=_text(payload.get("target_label")) or "",
            axis_names=_terms(payload.get("axis_names")),
            comparable=payload.get("comparable") is True,
            incomparability_reasons=_terms(
                payload.get("incomparability_reasons")
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "baseline_label": self.baseline_label,
            "target_label": self.target_label,
            "axis_names": list(self.axis_names),
            "comparable": self.comparable,
            "incomparability_reasons": list(self.incomparability_reasons),
        }


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

    def __post_init__(self) -> None:
        if not _text(self.outcome) or not _text(self.result_text):
            raise ValueError("scientific result requires outcome and result text")
        if self.direction not in SCIENTIFIC_RESULT_DIRECTIONS:
            raise ValueError(f"unsupported scientific result direction: {self.direction}")
        if self.result_kind not in SCIENTIFIC_RESULT_KINDS:
            raise ValueError(f"unsupported scientific result kind: {self.result_kind}")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ScientificResult":
        return cls(
            outcome=_text(payload.get("outcome")) or "",
            value=_scientific_scalar(payload.get("value")),
            unit=_text(payload.get("unit")),
            direction=_choice(
                payload.get("direction"), SCIENTIFIC_RESULT_DIRECTIONS, "unknown"
            ),
            result_text=_text(payload.get("result_text")) or "",
            baseline_value=_scientific_scalar(payload.get("baseline_value")),
            target_value=_scientific_scalar(payload.get("target_value")),
            result_kind=_choice(
                payload.get("result_kind"), SCIENTIFIC_RESULT_KINDS, "observed"
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "value": self.value,
            "baseline_value": self.baseline_value,
            "target_value": self.target_value,
            "unit": self.unit,
            "direction": self.direction,
            "result_text": self.result_text,
            "result_kind": self.result_kind,
        }


@dataclass(frozen=True)
class ScientificContext:
    """Material, sample, process, and test context for one scientific fact."""

    material: tuple[ScientificAttribute, ...] = ()
    sample: tuple[ScientificAttribute, ...] = ()
    process: tuple[ScientificAttribute, ...] = ()
    test: tuple[ScientificAttribute, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ScientificContext":
        return cls(
            material=_attributes(payload.get("material")),
            sample=_attributes(payload.get("sample")),
            process=_attributes(payload.get("process")),
            test=_attributes(payload.get("test")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "material": [item.to_record() for item in self.material],
            "sample": [item.to_record() for item in self.sample],
            "process": [item.to_record() for item in self.process],
            "test": [item.to_record() for item in self.test],
        }

    @property
    def has_content(self) -> bool:
        return bool(self.material or self.sample or self.process or self.test)


def _attributes(value: Any) -> tuple[ScientificAttribute, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        ScientificAttribute.from_mapping(item)
        for item in value
        if isinstance(item, Mapping)
    )


def _scientific_scalar(value: Any) -> ScientificScalar | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return _text(value)


def _terms(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        items = value.values()
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = (value,)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return tuple(normalized)


def _choice(value: Any, allowed: frozenset[str], default: str) -> str:
    normalized = (_text(value) or "").lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else default


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
