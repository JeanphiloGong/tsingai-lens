"""Reusable, source-grounded paper experiment records.

This module deliberately has no Objective, Collection, SQLAlchemy, or HTTP
dependency.  A paper experiment is reusable research state; an analysis later
selects the parts it needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from domain.core.scientific_fact import ScientificAttribute, ScientificVariable


PAPER_EXPERIMENT_DESIGN_TYPES = frozenset(
    {"parallel", "factorial", "dose_response", "observational", "unknown"}
)
PAPER_EXPERIMENT_IDENTITY_STATUSES = frozenset(
    {"identified", "partial", "unknown"}
)
PAPER_EXPERIMENT_BINDING_STATUSES = frozenset({"draft", "partial", "bound"})
RELATION_STATUSES = frozenset({"direct", "derived", "uncertain", "conflict"})
MEASUREMENT_RESULT_KINDS = frozenset(
    {"measured", "observed", "simulated", "predicted", "unknown"}
)
COMPARISON_BASIS = frozenset({"reported", "derived"})
COMPARISON_DIRECTIONS = frozenset(
    {"increase", "decrease", "no_change", "mixed", "unknown"}
)
COMPARISON_STATUSES = frozenset(
    {"ready", "insufficient_context", "non_comparable"}
)
INTERPRETATION_KINDS = frozenset(
    {"result_summary", "mechanism_hypothesis", "limitation"}
)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(item for item in (_text(item) for item in value) if item)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _attributes(value: Any) -> tuple[ScientificAttribute, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        ScientificAttribute.from_mapping(item)
        for item in value
        if isinstance(item, Mapping)
    )


def _variables(value: Any) -> tuple[ScientificVariable, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        ScientificVariable.from_mapping(item)
        for item in value
        if isinstance(item, Mapping)
    )


@dataclass(frozen=True)
class SourceReference:
    """Immutable pointer to a prepared Source; it does not assemble facts."""

    document_id: str
    source_fingerprint: str
    source_kind: str
    source_ref: str
    quote: str

    def __post_init__(self) -> None:
        if not all(
            _text(value)
            for value in (
                self.document_id,
                self.source_fingerprint,
                self.source_kind,
                self.source_ref,
                self.quote,
            )
        ):
            raise ValueError("source reference requires document, fingerprint, ref, and quote")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SourceReference":
        return cls(
            document_id=_text(payload.get("document_id")),
            source_fingerprint=_text(payload.get("source_fingerprint")),
            source_kind=_text(payload.get("source_kind")),
            source_ref=_text(payload.get("source_ref")),
            quote=_text(payload.get("quote")),
        )

    def to_record(self) -> dict[str, str]:
        return {
            "document_id": self.document_id,
            "source_fingerprint": self.source_fingerprint,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "quote": self.quote,
        }


@dataclass(frozen=True)
class ExperimentalVariant:
    """An experimental object or group inside one PaperExperiment revision."""

    variant_key: str
    variant_label: str
    subject_attributes: tuple[ScientificAttribute, ...] = ()
    intervention_attributes: tuple[ScientificAttribute, ...] = ()
    state: tuple[ScientificAttribute, ...] = ()
    population_scope: Mapping[str, Any] | None = None
    source_refs: tuple[SourceReference, ...] = ()
    binding_source_refs: tuple[SourceReference, ...] = ()
    binding_status: str = "uncertain"
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _text(self.variant_key) or not _text(self.variant_label):
            raise ValueError("experimental variant requires key and label")
        if self.binding_status not in RELATION_STATUSES:
            raise ValueError(f"unsupported variant binding status: {self.binding_status}")
        object.__setattr__(self, "notes", _strings(self.notes))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExperimentalVariant":
        return cls(
            variant_key=_text(payload.get("variant_key") or payload.get("variant_id")),
            variant_label=_text(payload.get("variant_label")),
            subject_attributes=_attributes(payload.get("subject_attributes")),
            intervention_attributes=_attributes(payload.get("intervention_attributes")),
            state=_attributes(payload.get("state")),
            population_scope=(
                _mapping(payload.get("population_scope"))
                if payload.get("population_scope") is not None
                else None
            ),
            source_refs=tuple(
                SourceReference.from_mapping(item)
                for item in payload.get("source_refs") or ()
                if isinstance(item, Mapping)
            ),
            binding_source_refs=tuple(
                SourceReference.from_mapping(item)
                for item in payload.get("binding_source_refs") or ()
                if isinstance(item, Mapping)
            ),
            binding_status=_text(payload.get("binding_status")) or "uncertain",
            notes=_strings(payload.get("notes")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "variant_key": self.variant_key,
            "variant_label": self.variant_label,
            "subject_attributes": [item.to_record() for item in self.subject_attributes],
            "intervention_attributes": [
                item.to_record() for item in self.intervention_attributes
            ],
            "state": [item.to_record() for item in self.state],
            "population_scope": dict(self.population_scope or {}),
            "source_refs": [item.to_record() for item in self.source_refs],
            "binding_source_refs": [item.to_record() for item in self.binding_source_refs],
            "binding_status": self.binding_status,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ExperimentTestCondition:
    """A test or characterization method and its applicable parameters."""

    test_key: str
    test_type: str
    parameters: tuple[ScientificAttribute, ...] = ()
    population_scope: Mapping[str, Any] | None = None
    source_refs: tuple[SourceReference, ...] = ()
    binding_status: str = "uncertain"
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _text(self.test_key) or not _text(self.test_type):
            raise ValueError("test condition requires key and type")
        if self.binding_status not in RELATION_STATUSES:
            raise ValueError(f"unsupported test binding status: {self.binding_status}")
        object.__setattr__(self, "notes", _strings(self.notes))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExperimentTestCondition":
        return cls(
            test_key=_text(payload.get("test_key") or payload.get("test_condition_id")),
            test_type=_text(payload.get("test_type") or payload.get("property_type")),
            parameters=_attributes(payload.get("parameters")),
            population_scope=(
                _mapping(payload.get("population_scope"))
                if payload.get("population_scope") is not None
                else None
            ),
            source_refs=tuple(
                SourceReference.from_mapping(item)
                for item in payload.get("source_refs") or ()
                if isinstance(item, Mapping)
            ),
            binding_status=_text(payload.get("binding_status")) or "uncertain",
            notes=_strings(payload.get("notes")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "test_key": self.test_key,
            "test_type": self.test_type,
            "parameters": [item.to_record() for item in self.parameters],
            "population_scope": dict(self.population_scope or {}),
            "source_refs": [item.to_record() for item in self.source_refs],
            "binding_status": self.binding_status,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ExperimentMeasurementResult:
    """One reported outcome at a declared measurement scope."""

    measurement_key: str
    outcome: str
    variant_key: str | None
    test_key: str | None
    value: Any = None
    unit: str | None = None
    result_text: str | None = None
    statistics: Mapping[str, Any] = field(default_factory=dict)
    measurement_scope: Mapping[str, Any] = field(default_factory=dict)
    result_kind: str = "measured"
    source_refs: tuple[SourceReference, ...] = ()
    binding_source_refs: tuple[SourceReference, ...] = ()
    binding_status: str = "uncertain"
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _text(self.measurement_key) or not _text(self.outcome):
            raise ValueError("measurement requires key and outcome")
        if self.value is None and not _text(self.result_text):
            raise ValueError("measurement requires value or result_text")
        if self.result_kind not in MEASUREMENT_RESULT_KINDS:
            raise ValueError(f"unsupported measurement result kind: {self.result_kind}")
        if self.binding_status not in RELATION_STATUSES:
            raise ValueError(f"unsupported measurement binding status: {self.binding_status}")
        object.__setattr__(self, "notes", _strings(self.notes))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExperimentMeasurementResult":
        return cls(
            measurement_key=_text(
                payload.get("measurement_key") or payload.get("measurement_id") or payload.get("result_id")
            ),
            outcome=_text(payload.get("outcome") or payload.get("property_normalized")),
            variant_key=_text(payload.get("variant_key") or payload.get("variant_id")) or None,
            test_key=_text(payload.get("test_key") or payload.get("test_condition_id")) or None,
            value=payload.get("value", payload.get("value_numeric")),
            unit=_text(payload.get("unit")) or None,
            result_text=_text(payload.get("result_text") or payload.get("value_text")) or None,
            statistics=_mapping(payload.get("statistics")),
            measurement_scope=_mapping(payload.get("measurement_scope")),
            result_kind=_text(payload.get("result_kind")) or "measured",
            source_refs=tuple(
                SourceReference.from_mapping(item)
                for item in payload.get("source_refs") or ()
                if isinstance(item, Mapping)
            ),
            binding_source_refs=tuple(
                SourceReference.from_mapping(item)
                for item in payload.get("binding_source_refs") or ()
                if isinstance(item, Mapping)
            ),
            binding_status=_text(payload.get("binding_status")) or "uncertain",
            notes=_strings(payload.get("notes")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "measurement_key": self.measurement_key,
            "outcome": self.outcome,
            "variant_key": self.variant_key,
            "test_key": self.test_key,
            "value": self.value,
            "unit": self.unit,
            "result_text": self.result_text,
            "statistics": dict(self.statistics),
            "measurement_scope": dict(self.measurement_scope),
            "result_kind": self.result_kind,
            "source_refs": [item.to_record() for item in self.source_refs],
            "binding_source_refs": [item.to_record() for item in self.binding_source_refs],
            "binding_status": self.binding_status,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ExperimentComparison:
    """A paper-reported or explicitly derived comparison between variants."""

    comparison_key: str
    baseline_variant_key: str
    target_variant_key: str
    outcome: str
    baseline_measurement_keys: tuple[str, ...]
    target_measurement_keys: tuple[str, ...]
    changed_variables: tuple[ScientificVariable, ...] = ()
    matched_conditions: tuple[ScientificAttribute, ...] = ()
    basis: str = "reported"
    direction: str = "unknown"
    reported_statement: str | None = None
    attribution_scope: str = "undetermined"
    status: str = "insufficient_context"
    reasons: tuple[str, ...] = ()
    source_refs: tuple[SourceReference, ...] = ()
    binding_source_refs: tuple[SourceReference, ...] = ()
    relation_status: str = "uncertain"

    def __post_init__(self) -> None:
        if not all(
            _text(value)
            for value in (
                self.comparison_key,
                self.baseline_variant_key,
                self.target_variant_key,
                self.outcome,
            )
        ):
            raise ValueError("comparison requires keys and outcome")
        if self.basis not in COMPARISON_BASIS:
            raise ValueError(f"unsupported comparison basis: {self.basis}")
        if self.direction not in COMPARISON_DIRECTIONS:
            raise ValueError(f"unsupported comparison direction: {self.direction}")
        if self.status not in COMPARISON_STATUSES:
            raise ValueError(f"unsupported comparison status: {self.status}")
        if self.relation_status not in RELATION_STATUSES:
            raise ValueError(f"unsupported comparison relation status: {self.relation_status}")
        if not self.baseline_measurement_keys or not self.target_measurement_keys:
            raise ValueError("comparison requires measurements on both sides")
        object.__setattr__(self, "reasons", _strings(self.reasons))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExperimentComparison":
        return cls(
            comparison_key=_text(payload.get("comparison_key") or payload.get("comparison_id")),
            baseline_variant_key=_text(payload.get("baseline_variant_key") or payload.get("baseline_variant_id")),
            target_variant_key=_text(payload.get("target_variant_key") or payload.get("target_variant_id")),
            outcome=_text(payload.get("outcome")),
            baseline_measurement_keys=_strings(
                payload.get("baseline_measurement_keys") or payload.get("baseline_measurement_ids")
            ),
            target_measurement_keys=_strings(
                payload.get("target_measurement_keys") or payload.get("target_measurement_ids")
            ),
            changed_variables=_variables(payload.get("changed_variables")),
            matched_conditions=_attributes(payload.get("matched_conditions")),
            basis=_text(payload.get("basis")) or "reported",
            direction=_text(payload.get("direction")) or "unknown",
            reported_statement=_text(payload.get("reported_statement")) or None,
            attribution_scope=_text(payload.get("attribution_scope")) or "undetermined",
            status=_text(payload.get("status")) or "insufficient_context",
            reasons=_strings(payload.get("reasons")),
            source_refs=tuple(
                SourceReference.from_mapping(item)
                for item in payload.get("source_refs") or ()
                if isinstance(item, Mapping)
            ),
            binding_source_refs=tuple(
                SourceReference.from_mapping(item)
                for item in payload.get("binding_source_refs") or ()
                if isinstance(item, Mapping)
            ),
            relation_status=_text(payload.get("relation_status")) or "uncertain",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "comparison_key": self.comparison_key,
            "baseline_variant_key": self.baseline_variant_key,
            "target_variant_key": self.target_variant_key,
            "outcome": self.outcome,
            "baseline_measurement_keys": list(self.baseline_measurement_keys),
            "target_measurement_keys": list(self.target_measurement_keys),
            "changed_variables": [item.to_record() for item in self.changed_variables],
            "matched_conditions": [item.to_record() for item in self.matched_conditions],
            "basis": self.basis,
            "direction": self.direction,
            "reported_statement": self.reported_statement,
            "attribution_scope": self.attribution_scope,
            "status": self.status,
            "reasons": list(self.reasons),
            "source_refs": [item.to_record() for item in self.source_refs],
            "binding_source_refs": [item.to_record() for item in self.binding_source_refs],
            "relation_status": self.relation_status,
        }


@dataclass(frozen=True)
class ReportedInterpretation:
    statement: str
    kind: str
    measurement_keys: tuple[str, ...] = ()
    comparison_keys: tuple[str, ...] = ()
    source_refs: tuple[SourceReference, ...] = ()

    def __post_init__(self) -> None:
        if not _text(self.statement) or self.kind not in INTERPRETATION_KINDS:
            raise ValueError("reported interpretation requires statement and valid kind")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ReportedInterpretation":
        return cls(
            statement=_text(payload.get("statement")),
            kind=_text(payload.get("kind")) or "result_summary",
            measurement_keys=_strings(payload.get("measurement_keys") or payload.get("measurement_ids")),
            comparison_keys=_strings(payload.get("comparison_keys") or payload.get("comparison_ids")),
            source_refs=tuple(
                SourceReference.from_mapping(item)
                for item in payload.get("source_refs") or ()
                if isinstance(item, Mapping)
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "kind": self.kind,
            "measurement_keys": list(self.measurement_keys),
            "comparison_keys": list(self.comparison_keys),
            "source_refs": [item.to_record() for item in self.source_refs],
        }


@dataclass(frozen=True)
class PaperExperimentRevision:
    """The complete scientific content of one fixed experiment version."""

    experiment_id: str
    document_id: str
    experiment_version: int
    source_fingerprint: str
    label: str
    scope_description: str
    design_type: str = "unknown"
    identity_status: str = "unknown"
    binding_status: str = "draft"
    variants: tuple[ExperimentalVariant, ...] = ()
    test_conditions: tuple[ExperimentTestCondition, ...] = ()
    measurements: tuple[ExperimentMeasurementResult, ...] = ()
    comparisons: tuple[ExperimentComparison, ...] = ()
    reported_interpretations: tuple[ReportedInterpretation, ...] = ()
    source_refs: tuple[SourceReference, ...] = ()
    unresolved_issues: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not all(
            _text(value)
            for value in (
                self.experiment_id,
                self.document_id,
                self.source_fingerprint,
                self.label,
                self.scope_description,
            )
        ):
            raise ValueError("paper experiment requires identity and scope")
        if self.experiment_version < 1:
            raise ValueError("experiment version must be positive")
        if self.design_type not in PAPER_EXPERIMENT_DESIGN_TYPES:
            raise ValueError(f"unsupported experiment design type: {self.design_type}")
        if self.identity_status not in PAPER_EXPERIMENT_IDENTITY_STATUSES:
            raise ValueError(f"unsupported experiment identity status: {self.identity_status}")
        if self.binding_status not in PAPER_EXPERIMENT_BINDING_STATUSES:
            raise ValueError(f"unsupported experiment binding status: {self.binding_status}")

        variant_keys = [item.variant_key for item in self.variants]
        test_keys = [item.test_key for item in self.test_conditions]
        measurement_keys = [item.measurement_key for item in self.measurements]
        comparison_keys = [item.comparison_key for item in self.comparisons]
        for name, values in (
            ("variant", variant_keys),
            ("test", test_keys),
            ("measurement", measurement_keys),
            ("comparison", comparison_keys),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"paper experiment {name} keys must be unique")

        variant_set = set(variant_keys)
        test_set = set(test_keys)
        measurement_by_key = {item.measurement_key: item for item in self.measurements}
        for measurement in self.measurements:
            if measurement.variant_key is not None and measurement.variant_key not in variant_set:
                raise ValueError("measurement references a variant outside its experiment")
            if measurement.test_key is not None and measurement.test_key not in test_set:
                raise ValueError("measurement references a test outside its experiment")
        for comparison in self.comparisons:
            if comparison.baseline_variant_key not in variant_set or comparison.target_variant_key not in variant_set:
                raise ValueError("comparison references a variant outside its experiment")
            references = (*comparison.baseline_measurement_keys, *comparison.target_measurement_keys)
            if any(key not in measurement_by_key for key in references):
                raise ValueError("comparison references a measurement outside its experiment")
            if any(measurement_by_key[key].outcome != comparison.outcome for key in references):
                raise ValueError("comparison measurements must share the comparison outcome")
        for interpretation in self.reported_interpretations:
            if any(key not in measurement_by_key for key in interpretation.measurement_keys):
                raise ValueError("interpretation references a measurement outside its experiment")
            if any(key not in set(comparison_keys) for key in interpretation.comparison_keys):
                raise ValueError("interpretation references a comparison outside its experiment")

        object.__setattr__(
            self,
            "unresolved_issues",
            tuple(dict(item) for item in self.unresolved_issues if isinstance(item, Mapping)),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperExperimentRevision":
        return cls(
            experiment_id=_text(payload.get("experiment_id")),
            document_id=_text(payload.get("document_id")),
            experiment_version=int(payload.get("experiment_version") or 0),
            source_fingerprint=_text(payload.get("source_fingerprint")),
            label=_text(payload.get("label")),
            scope_description=_text(payload.get("scope_description")),
            design_type=_text(payload.get("design_type")) or "unknown",
            identity_status=_text(payload.get("identity_status")) or "unknown",
            binding_status=_text(payload.get("binding_status")) or "draft",
            variants=tuple(
                ExperimentalVariant.from_mapping(item)
                for item in payload.get("variants") or payload.get("experimental_variants") or ()
                if isinstance(item, Mapping)
            ),
            test_conditions=tuple(
                ExperimentTestCondition.from_mapping(item)
                for item in payload.get("test_conditions") or ()
                if isinstance(item, Mapping)
            ),
            measurements=tuple(
                ExperimentMeasurementResult.from_mapping(item)
                for item in payload.get("measurements") or ()
                if isinstance(item, Mapping)
            ),
            comparisons=tuple(
                ExperimentComparison.from_mapping(item)
                for item in payload.get("comparisons") or ()
                if isinstance(item, Mapping)
            ),
            reported_interpretations=tuple(
                ReportedInterpretation.from_mapping(item)
                for item in payload.get("reported_interpretations") or ()
                if isinstance(item, Mapping)
            ),
            source_refs=tuple(
                SourceReference.from_mapping(item)
                for item in payload.get("source_refs") or ()
                if isinstance(item, Mapping)
            ),
            unresolved_issues=tuple(
                dict(item)
                for item in payload.get("unresolved_issues") or ()
                if isinstance(item, Mapping)
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "document_id": self.document_id,
            "experiment_version": self.experiment_version,
            "source_fingerprint": self.source_fingerprint,
            "label": self.label,
            "scope_description": self.scope_description,
            "design_type": self.design_type,
            "identity_status": self.identity_status,
            "binding_status": self.binding_status,
            "variants": [item.to_record() for item in self.variants],
            "test_conditions": [item.to_record() for item in self.test_conditions],
            "measurements": [item.to_record() for item in self.measurements],
            "comparisons": [item.to_record() for item in self.comparisons],
            "reported_interpretations": [
                item.to_record() for item in self.reported_interpretations
            ],
            "source_refs": [item.to_record() for item in self.source_refs],
            "unresolved_issues": [dict(item) for item in self.unresolved_issues],
        }


__all__ = [
    "COMPARISON_BASIS",
    "COMPARISON_DIRECTIONS",
    "COMPARISON_STATUSES",
    "ExperimentComparison",
    "ExperimentMeasurementResult",
    "ExperimentTestCondition",
    "ExperimentalVariant",
    "INTERPRETATION_KINDS",
    "MEASUREMENT_RESULT_KINDS",
    "PAPER_EXPERIMENT_BINDING_STATUSES",
    "PAPER_EXPERIMENT_DESIGN_TYPES",
    "PAPER_EXPERIMENT_IDENTITY_STATUSES",
    "PaperExperimentRevision",
    "RELATION_STATUSES",
    "ReportedInterpretation",
    "SourceReference",
]
