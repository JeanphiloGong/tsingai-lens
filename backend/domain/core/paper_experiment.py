"""Reusable, source-grounded paper experiment records.

This module deliberately has no Objective, Collection, SQLAlchemy, or HTTP
dependency.  A paper experiment is reusable research state; an analysis later
selects the parts it needs.
"""

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from domain.core.scientific_fact import (
    ScientificAttribute,
    ScientificVariable,
)

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


def outcome_labels_compatible(left: Any, right: Any) -> bool:
    """Compare labels while allowing a display-unit annotation only.

    A table header may call a result ``elongation (%)`` while the prose calls
    it ``elongation``.  That is a presentation difference, not a new outcome.
    In contrast, ``strength`` and ``tensile strength`` are distinct labels
    unless the paper provides an explicit alias; a token-subset comparison
    would silently collapse those outcomes.
    """

    unit_tokens = {
        "%", "pa", "kpa", "mpa", "gpa", "hz", "nm", "um", "mm", "cm",
        "m", "s", "ms", "min", "h", "c", "f", "k", "j", "w", "n",
        "kg", "g", "mol", "wt", "vol", "ppm", "ppb", "rad", "deg",
        "bar", "mbar", "hv", "hb", "hbs", "hbd",
    }

    def normalize(value: Any) -> str:
        text = unicodedata.normalize("NFKC", _text(value)).casefold().strip()

        def remove_unit_group(inner: str, original: str) -> str:
            inner = inner.strip()
            if not inner:
                return " "
            if "%" in inner or "°" in inner:
                return " "
            tokens = re.findall(r"[^\W_]+", inner, flags=re.UNICODE)
            if not tokens:
                return original
            normalized_tokens = {
                re.sub(r"\d+$", "", token) if not token.isnumeric() else token
                for token in tokens
            }
            # Numeric values plus recognised unit tokens are display metadata,
            # e.g. ``(MPa)``, ``(10 mm/s)``, ``(J/mm3)`` or ``(deg)``.
            if all(
                token.isnumeric() or token in unit_tokens
                for token in normalized_tokens
            ):
                return " "
            return original

        text = re.sub(
            r"\(([^()]*)\)|\[([^\[\]]*)\]",
            lambda match: remove_unit_group(
                match.group(1) or match.group(2) or "",
                match.group(0),
            ),
            text,
        )
        # The bracket callback above uses a synthetic match; remove a trailing
        # standalone percent/unit marker as well (``elongation %``).
        tokens = re.findall(r"[^\W_]+|%", text, flags=re.UNICODE)
        while tokens and tokens[-1] in unit_tokens | {"%"}:
            tokens.pop()
        return " ".join(tokens)

    left_label = normalize(left)
    right_label = normalize(right)
    return bool(left_label and right_label and left_label == right_label)


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


@dataclass(frozen=True)
class ExperimentalVariant:
    """An experimental object or group inside one PaperExperiment revision.

    ``identity_specificity`` and ``missing_dimensions`` are source/model
    declarations about how completely the object was identified.  They are
    deliberately distinct from ``binding_status``: the latter is computed by
    the application after source and relationship checks.  Keeping both lets
    a partial record remain auditable instead of silently becoming a generic
    sample or an apparently exact variant.
    """

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
    identity_specificity: str = "unknown"
    missing_dimensions: tuple[str, ...] = ()
    identity_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _text(self.variant_key) or not _text(self.variant_label):
            raise ValueError("experimental variant requires key and label")
        if self.binding_status not in RELATION_STATUSES:
            raise ValueError(f"unsupported variant binding status: {self.binding_status}")
        object.__setattr__(self, "notes", _strings(self.notes))
        object.__setattr__(
            self,
            "identity_specificity",
            _text(self.identity_specificity) or "unknown",
        )
        object.__setattr__(self, "missing_dimensions", _strings(self.missing_dimensions))
        object.__setattr__(self, "identity_evidence", _strings(self.identity_evidence))


@dataclass(frozen=True)
class ExperimentTestCondition:
    """A test or characterization method and its applicable parameters.

    A paper may only identify a category such as ``mechanical test``.  The
    protocol metadata records that limitation without promoting the category
    to an exact protocol.  ``binding_status`` remains the service-owned
    relationship result.
    """

    test_key: str
    test_type: str
    parameters: tuple[ScientificAttribute, ...] = ()
    population_scope: Mapping[str, Any] | None = None
    source_refs: tuple[SourceReference, ...] = ()
    binding_status: str = "uncertain"
    notes: tuple[str, ...] = ()
    protocol_specificity: str = "unknown"
    test_identity_status: str = "unknown"
    protocol_completeness: str = "unknown"
    missing_parameters: tuple[str, ...] = ()
    method: str | None = None
    standard: str | None = None
    outcome_scope: tuple[str, ...] = ()
    binding_source_refs: tuple[SourceReference, ...] = ()
    protocol_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _text(self.test_key) or not _text(self.test_type):
            raise ValueError("test condition requires key and type")
        if self.binding_status not in RELATION_STATUSES:
            raise ValueError(f"unsupported test binding status: {self.binding_status}")
        object.__setattr__(self, "notes", _strings(self.notes))
        object.__setattr__(
            self,
            "protocol_specificity",
            _text(self.protocol_specificity) or "unknown",
        )
        object.__setattr__(
            self,
            "test_identity_status",
            _text(self.test_identity_status) or "unknown",
        )
        object.__setattr__(
            self,
            "protocol_completeness",
            _text(self.protocol_completeness) or "unknown",
        )
        object.__setattr__(self, "missing_parameters", _strings(self.missing_parameters))
        object.__setattr__(self, "method", _text(self.method) or None)
        object.__setattr__(self, "standard", _text(self.standard) or None)
        object.__setattr__(self, "outcome_scope", _strings(self.outcome_scope))
        object.__setattr__(self, "protocol_evidence", _strings(self.protocol_evidence))


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
            if any(
                not outcome_labels_compatible(
                    measurement_by_key[key].outcome,
                    comparison.outcome,
                )
                for key in references
            ):
                raise ValueError("comparison measurements must share the comparison outcome")
        for interpretation in self.reported_interpretations:
            if any(key not in measurement_by_key for key in interpretation.measurement_keys):
                raise ValueError("interpretation references a measurement outside its experiment")
            if any(key not in set(comparison_keys) for key in interpretation.comparison_keys):
                raise ValueError("interpretation references a comparison outside its experiment")

        object.__setattr__(
            self,
            "unresolved_issues",
            deepcopy(
                tuple(
                    dict(item)
                    for item in self.unresolved_issues
                    if isinstance(item, Mapping)
                )
            ),
        )


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
    "outcome_labels_compatible",
]
