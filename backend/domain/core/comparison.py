from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json
import math
from typing import Any, Final, Mapping

from domain.shared.enums import (
    COMPARABILITY_STATUS_COMPARABLE,
    COMPARABILITY_STATUS_INSUFFICIENT,
    COMPARABILITY_STATUS_LIMITED,
    COMPARABILITY_STATUS_NOT_COMPARABLE,
    EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE,
    EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
    EPISTEMIC_UNRESOLVED,
    TRACEABILITY_STATUS_DIRECT,
    TRACEABILITY_STATUS_MISSING,
)


SCALAR_LIKE_RESULT_TYPES: Final[frozenset[str]] = frozenset(
    {"scalar", "retention", "fitted_value", "optimum"}
)
COMPARABLE_RESULT_NORMALIZATION_VERSION: Final[str] = "comparable_result_v1"
COMPARISON_ROW_PROJECTION_VERSION: Final[str] = "comparison_row_v1"
COLLECTION_COMPARISON_POLICY_FAMILY: Final[str] = "default_collection_comparison_policy"
COLLECTION_COMPARISON_POLICY_VERSION: Final[str] = "comparison_policy_v1"
COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED: Final[str] = (
    "policy_family_changed"
)
COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED: Final[str] = (
    "policy_version_changed"
)
COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED: Final[str] = (
    "comparable_result_normalization_version_changed"
)
COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED: Final[str] = (
    "assessment_input_fingerprint_changed"
)
DEFAULT_COLLECTION_REASSESSMENT_TRIGGERS: Final[tuple[str, ...]] = (
    COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED,
    COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED,
)
PBF_PROCESS_CONTEXT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "laser_power_w",
        "scan_speed_mm_s",
        "layer_thickness_um",
        "hatch_spacing_um",
        "spot_size_um",
        "energy_density_j_mm3",
        "energy_density_origin",
        "scan_strategy",
        "build_orientation",
        "preheat_temperature_c",
        "shielding_gas",
        "oxygen_level_ppm",
        "powder_size_distribution_um",
        "post_treatment_summary",
    }
)
PBF_TENSILE_STYLE_PROPERTIES: Final[frozenset[str]] = frozenset(
    {
        "strength",
        "tensile_strength",
        "yield_strength",
        "elongation",
        "modulus",
    }
)
PBF_ORIENTATION_SENSITIVE_PROPERTIES: Final[frozenset[str]] = frozenset(
    {
        *PBF_TENSILE_STYLE_PROPERTIES,
        "fatigue_life",
        "residual_stress",
    }
)


@dataclass(frozen=True)
class ContextBinding:
    variant_id: str | None
    baseline_id: str | None
    test_condition_id: str | None


@dataclass(frozen=True)
class NormalizedComparisonContext:
    material_system_normalized: str
    process_normalized: str | None
    baseline_normalized: str | None
    test_condition_normalized: str | None


@dataclass(frozen=True)
class ComparisonAxis:
    axis_name: str | None
    axis_value: str | float | int | None
    axis_unit: str | None


@dataclass(frozen=True)
class ResultValue:
    property_normalized: str
    result_type: str
    numeric_value: float | None
    unit: str | None
    summary: str
    statistic_type: str | None = None
    uncertainty: str | None = None


@dataclass(frozen=True)
class EvidenceTrace:
    direct_anchor_ids: tuple[str, ...]
    contextual_anchor_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    structure_feature_ids: tuple[str, ...]
    characterization_observation_ids: tuple[str, ...]
    traceability_status: str


@dataclass(frozen=True)
class ComparableResult:
    comparable_result_id: str
    source_result_id: str
    source_document_id: str
    binding: ContextBinding
    normalized_context: NormalizedComparisonContext
    axis: ComparisonAxis
    value: ResultValue
    evidence: EvidenceTrace
    variant_label: str | None
    baseline_reference: str | None
    result_source_type: str | None
    epistemic_status: str
    normalization_version: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ComparableResult":
        binding = _normalize_mapping(payload.get("binding"))
        normalized_context = _normalize_mapping(payload.get("normalized_context"))
        axis = _normalize_mapping(payload.get("axis"))
        value = _normalize_mapping(payload.get("value"))
        evidence = _normalize_mapping(payload.get("evidence"))
        return cls(
            comparable_result_id=_normalize_text(payload.get("comparable_result_id")) or "",
            source_result_id=_normalize_text(payload.get("source_result_id")) or "",
            source_document_id=_normalize_text(payload.get("source_document_id")) or "",
            binding=ContextBinding(
                variant_id=_normalize_text(binding.get("variant_id")),
                baseline_id=_normalize_text(binding.get("baseline_id")),
                test_condition_id=_normalize_text(binding.get("test_condition_id")),
            ),
            normalized_context=NormalizedComparisonContext(
                material_system_normalized=_normalize_text(
                    normalized_context.get("material_system_normalized")
                )
                or "unspecified material system",
                process_normalized=_normalize_text(normalized_context.get("process_normalized")),
                baseline_normalized=_normalize_text(normalized_context.get("baseline_normalized")),
                test_condition_normalized=_normalize_text(
                    normalized_context.get("test_condition_normalized")
                ),
            ),
            axis=ComparisonAxis(
                axis_name=_normalize_text(axis.get("axis_name")),
                axis_value=_normalize_scalar_or_text(axis.get("axis_value")),
                axis_unit=_normalize_text(axis.get("axis_unit")),
            ),
            value=ResultValue(
                property_normalized=_normalize_text(value.get("property_normalized"))
                or "qualitative",
                result_type=_normalize_text(value.get("result_type")) or "scalar",
                numeric_value=_normalize_optional_float(value.get("numeric_value")),
                unit=_normalize_text(value.get("unit")),
                summary=_normalize_text(value.get("summary")) or "Result reported",
                statistic_type=_normalize_text(value.get("statistic_type")),
                uncertainty=_normalize_text(value.get("uncertainty")),
            ),
            evidence=EvidenceTrace(
                direct_anchor_ids=_normalize_string_tuple(evidence.get("direct_anchor_ids")),
                contextual_anchor_ids=_normalize_string_tuple(
                    evidence.get("contextual_anchor_ids")
                ),
                evidence_ids=_normalize_string_tuple(evidence.get("evidence_ids")),
                structure_feature_ids=_normalize_string_tuple(
                    evidence.get("structure_feature_ids")
                ),
                characterization_observation_ids=_normalize_string_tuple(
                    evidence.get("characterization_observation_ids")
                ),
                traceability_status=_normalize_text(evidence.get("traceability_status"))
                or TRACEABILITY_STATUS_MISSING,
            ),
            variant_label=_normalize_text(payload.get("variant_label")),
            baseline_reference=_normalize_text(payload.get("baseline_reference")),
            result_source_type=_normalize_text(payload.get("result_source_type")),
            epistemic_status=_normalize_text(payload.get("epistemic_status"))
            or EPISTEMIC_UNRESOLVED,
            normalization_version=_normalize_text(payload.get("normalization_version"))
            or COMPARABLE_RESULT_NORMALIZATION_VERSION,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "comparable_result_id": self.comparable_result_id,
            "source_result_id": self.source_result_id,
            "source_document_id": self.source_document_id,
            "binding": {
                "variant_id": self.binding.variant_id,
                "baseline_id": self.binding.baseline_id,
                "test_condition_id": self.binding.test_condition_id,
            },
            "normalized_context": {
                "material_system_normalized": self.normalized_context.material_system_normalized,
                "process_normalized": self.normalized_context.process_normalized,
                "baseline_normalized": self.normalized_context.baseline_normalized,
                "test_condition_normalized": self.normalized_context.test_condition_normalized,
            },
            "axis": {
                "axis_name": self.axis.axis_name,
                "axis_value": self.axis.axis_value,
                "axis_unit": self.axis.axis_unit,
            },
            "value": {
                "property_normalized": self.value.property_normalized,
                "result_type": self.value.result_type,
                "numeric_value": self.value.numeric_value,
                "unit": self.value.unit,
                "summary": self.value.summary,
                "statistic_type": self.value.statistic_type,
                "uncertainty": self.value.uncertainty,
            },
            "evidence": {
                "direct_anchor_ids": list(self.evidence.direct_anchor_ids),
                "contextual_anchor_ids": list(self.evidence.contextual_anchor_ids),
                "evidence_ids": list(self.evidence.evidence_ids),
                "structure_feature_ids": list(self.evidence.structure_feature_ids),
                "characterization_observation_ids": list(
                    self.evidence.characterization_observation_ids
                ),
                "traceability_status": self.evidence.traceability_status,
            },
            "variant_label": self.variant_label,
            "baseline_reference": self.baseline_reference,
            "result_source_type": self.result_source_type,
            "epistemic_status": self.epistemic_status,
            "normalization_version": self.normalization_version,
        }


@dataclass(frozen=True)
class ComparisonAssessment:
    missing_critical_context: tuple[str, ...]
    comparability_basis: tuple[str, ...]
    comparability_warnings: tuple[str, ...]
    comparability_status: str
    requires_expert_review: bool
    assessment_epistemic_status: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ComparisonAssessment":
        return cls(
            missing_critical_context=_normalize_string_tuple(
                payload.get("missing_critical_context")
            ),
            comparability_basis=_normalize_string_tuple(payload.get("comparability_basis")),
            comparability_warnings=_normalize_string_tuple(
                payload.get("comparability_warnings")
            ),
            comparability_status=_normalize_text(payload.get("comparability_status"))
            or COMPARABILITY_STATUS_LIMITED,
            requires_expert_review=_normalize_bool(payload.get("requires_expert_review")),
            assessment_epistemic_status=_normalize_text(
                payload.get("assessment_epistemic_status")
            )
            or EPISTEMIC_UNRESOLVED,
        )

    def to_payload(self) -> dict[str, Any]:
        return self.to_record()

    def to_record(self) -> dict[str, Any]:
        return {
            "missing_critical_context": list(self.missing_critical_context),
            "comparability_basis": list(self.comparability_basis),
            "comparability_warnings": list(self.comparability_warnings),
            "comparability_status": self.comparability_status,
            "requires_expert_review": self.requires_expert_review,
            "assessment_epistemic_status": self.assessment_epistemic_status,
        }


@dataclass(frozen=True)
class CollectionComparableResult:
    collection_id: str
    comparable_result_id: str
    assessment: ComparisonAssessment
    epistemic_status: str
    included: bool
    sort_order: int | None = None
    policy_family: str = COLLECTION_COMPARISON_POLICY_FAMILY
    policy_version: str = COLLECTION_COMPARISON_POLICY_VERSION
    comparable_result_normalization_version: str = COMPARABLE_RESULT_NORMALIZATION_VERSION
    assessment_input_fingerprint: str = ""
    reassessment_triggers: tuple[str, ...] = DEFAULT_COLLECTION_REASSESSMENT_TRIGGERS

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CollectionComparableResult":
        return cls(
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            comparable_result_id=_normalize_text(payload.get("comparable_result_id")) or "",
            assessment=ComparisonAssessment.from_mapping(
                _normalize_mapping(payload.get("assessment"))
            ),
            epistemic_status=_normalize_text(payload.get("epistemic_status"))
            or EPISTEMIC_UNRESOLVED,
            included=_normalize_bool(payload.get("included")),
            sort_order=_normalize_optional_int(payload.get("sort_order")),
            policy_family=_normalize_text(payload.get("policy_family"))
            or COLLECTION_COMPARISON_POLICY_FAMILY,
            policy_version=_normalize_text(payload.get("policy_version"))
            or COLLECTION_COMPARISON_POLICY_VERSION,
            comparable_result_normalization_version=_normalize_text(
                payload.get("comparable_result_normalization_version")
            )
            or COMPARABLE_RESULT_NORMALIZATION_VERSION,
            assessment_input_fingerprint=_normalize_text(
                payload.get("assessment_input_fingerprint")
            )
            or "",
            reassessment_triggers=_normalize_string_tuple(payload.get("reassessment_triggers"))
            or DEFAULT_COLLECTION_REASSESSMENT_TRIGGERS,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "comparable_result_id": self.comparable_result_id,
            "assessment": self.assessment.to_record(),
            "epistemic_status": self.epistemic_status,
            "included": self.included,
            "sort_order": self.sort_order,
            "policy_family": self.policy_family,
            "policy_version": self.policy_version,
            "comparable_result_normalization_version": self.comparable_result_normalization_version,
            "assessment_input_fingerprint": self.assessment_input_fingerprint,
            "reassessment_triggers": list(self.reassessment_triggers),
        }


@dataclass(frozen=True)
class ComparisonRowRecord:
    row_id: str
    collection_id: str
    comparable_result_id: str
    source_document_id: str
    variant_id: str | None
    variant_label: str | None
    variable_axis: str | None
    variable_value: str | float | int | None
    baseline_reference: str | None
    result_source_type: str | None
    result_type: str
    result_summary: str
    supporting_evidence_ids: tuple[str, ...]
    supporting_anchor_ids: tuple[str, ...]
    characterization_observation_ids: tuple[str, ...]
    structure_feature_ids: tuple[str, ...]
    material_system_normalized: str
    process_normalized: str
    property_normalized: str
    baseline_normalized: str
    test_condition_normalized: str
    comparability_status: str
    comparability_warnings: tuple[str, ...]
    comparability_basis: tuple[str, ...]
    requires_expert_review: bool
    assessment_epistemic_status: str
    missing_critical_context: tuple[str, ...]
    value: float | None
    unit: str | None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ComparisonRowRecord":
        return cls(
            row_id=_normalize_text(payload.get("row_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            comparable_result_id=_normalize_text(payload.get("comparable_result_id")) or "",
            source_document_id=_normalize_text(payload.get("source_document_id")) or "",
            variant_id=_normalize_text(payload.get("variant_id")),
            variant_label=_normalize_text(payload.get("variant_label")),
            variable_axis=_normalize_text(payload.get("variable_axis")),
            variable_value=_normalize_scalar_or_text(payload.get("variable_value")),
            baseline_reference=_normalize_text(payload.get("baseline_reference")),
            result_source_type=_normalize_text(payload.get("result_source_type")),
            result_type=_normalize_text(payload.get("result_type")) or "scalar",
            result_summary=_normalize_text(payload.get("result_summary")) or "Result reported",
            supporting_evidence_ids=_normalize_string_tuple(payload.get("supporting_evidence_ids")),
            supporting_anchor_ids=_normalize_string_tuple(payload.get("supporting_anchor_ids")),
            characterization_observation_ids=_normalize_string_tuple(
                payload.get("characterization_observation_ids")
            ),
            structure_feature_ids=_normalize_string_tuple(payload.get("structure_feature_ids")),
            material_system_normalized=_normalize_text(payload.get("material_system_normalized"))
            or "unspecified material system",
            process_normalized=_normalize_text(payload.get("process_normalized"))
            or "unspecified process",
            property_normalized=_normalize_text(payload.get("property_normalized"))
            or "qualitative",
            baseline_normalized=_normalize_text(payload.get("baseline_normalized"))
            or "unspecified baseline",
            test_condition_normalized=_normalize_text(payload.get("test_condition_normalized"))
            or "unspecified test condition",
            comparability_status=_normalize_text(payload.get("comparability_status"))
            or COMPARABILITY_STATUS_LIMITED,
            comparability_warnings=_normalize_string_tuple(payload.get("comparability_warnings")),
            comparability_basis=_normalize_string_tuple(payload.get("comparability_basis")),
            requires_expert_review=_normalize_bool(payload.get("requires_expert_review")),
            assessment_epistemic_status=_normalize_text(payload.get("assessment_epistemic_status"))
            or EPISTEMIC_UNRESOLVED,
            missing_critical_context=_normalize_string_tuple(payload.get("missing_critical_context")),
            value=_normalize_optional_float(payload.get("value")),
            unit=_normalize_text(payload.get("unit")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "collection_id": self.collection_id,
            "comparable_result_id": self.comparable_result_id,
            "source_document_id": self.source_document_id,
            "variant_id": self.variant_id,
            "variant_label": self.variant_label,
            "variable_axis": self.variable_axis,
            "variable_value": self.variable_value,
            "baseline_reference": self.baseline_reference,
            "result_source_type": self.result_source_type,
            "result_type": self.result_type,
            "result_summary": self.result_summary,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "supporting_anchor_ids": list(self.supporting_anchor_ids),
            "characterization_observation_ids": list(self.characterization_observation_ids),
            "structure_feature_ids": list(self.structure_feature_ids),
            "material_system_normalized": self.material_system_normalized,
            "process_normalized": self.process_normalized,
            "property_normalized": self.property_normalized,
            "baseline_normalized": self.baseline_normalized,
            "test_condition_normalized": self.test_condition_normalized,
            "comparability_status": self.comparability_status,
            "comparability_warnings": list(self.comparability_warnings),
            "comparability_basis": list(self.comparability_basis),
            "requires_expert_review": self.requires_expert_review,
            "assessment_epistemic_status": self.assessment_epistemic_status,
            "missing_critical_context": list(self.missing_critical_context),
            "value": self.value,
            "unit": self.unit,
        }


def build_comparable_result_id(
    *,
    source_document_id: str,
    property_normalized: str,
    result_type: str,
    value_payload: Any,
    unit: str | None,
    result_source_type: str | None,
    traceability_status: str,
    variant_payload: Mapping[str, Any] | None,
    baseline_payload: Mapping[str, Any] | None,
    test_condition_payload: Mapping[str, Any] | None,
    normalization_version: str = COMPARABLE_RESULT_NORMALIZATION_VERSION,
) -> str:
    return _build_deterministic_id(
        "cres",
        {
            "source_document_id": source_document_id,
            "property_normalized": property_normalized,
            "result_type": result_type,
            "value_payload": value_payload,
            "unit": unit,
            "result_source_type": result_source_type,
            "traceability_status": traceability_status,
            "variant": variant_payload or {},
            "baseline": baseline_payload or {},
            "test_condition": test_condition_payload or {},
            "normalization_version": normalization_version,
        },
    )


def build_comparison_row_id(
    *,
    collection_id: str,
    comparable_result_id: str,
    projection_version: str = COMPARISON_ROW_PROJECTION_VERSION,
) -> str:
    return _build_deterministic_id(
        "cmp",
        {
            "collection_id": collection_id,
            "comparable_result_id": comparable_result_id,
            "projection_version": projection_version,
        },
    )


def build_collection_assessment_input_fingerprint(
    comparable_result: ComparableResult,
) -> str:
    return _build_deterministic_id(
        "cafp",
        {
            "comparable_result_id": comparable_result.comparable_result_id,
            "source_result_id": comparable_result.source_result_id,
            "source_document_id": comparable_result.source_document_id,
            "binding": {
                "variant_id": comparable_result.binding.variant_id,
                "baseline_id": comparable_result.binding.baseline_id,
                "test_condition_id": comparable_result.binding.test_condition_id,
            },
            "baseline_reference": comparable_result.baseline_reference,
            "result_type": comparable_result.value.result_type,
            "numeric_value": comparable_result.value.numeric_value,
            "summary": comparable_result.value.summary,
            "traceability_status": comparable_result.evidence.traceability_status,
            "structure_feature_ids": comparable_result.evidence.structure_feature_ids,
            "characterization_observation_ids": comparable_result.evidence.characterization_observation_ids,
        },
    )


def evaluate_collection_reassessment_reasons(
    scoped_result: CollectionComparableResult,
    comparable_result: ComparableResult,
    *,
    policy_family: str = COLLECTION_COMPARISON_POLICY_FAMILY,
    policy_version: str = COLLECTION_COMPARISON_POLICY_VERSION,
) -> tuple[str, ...]:
    active_triggers = scoped_result.reassessment_triggers or DEFAULT_COLLECTION_REASSESSMENT_TRIGGERS
    current_fingerprint = build_collection_assessment_input_fingerprint(comparable_result)
    reasons: list[str] = []
    if (
        COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED in active_triggers
        and scoped_result.policy_family != policy_family
    ):
        reasons.append(COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED)
    if (
        COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED in active_triggers
        and scoped_result.policy_version != policy_version
    ):
        reasons.append(COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED)
    if (
        COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED in active_triggers
        and scoped_result.comparable_result_normalization_version
        != comparable_result.normalization_version
    ):
        reasons.append(COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED)
    if (
        COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED in active_triggers
        and scoped_result.assessment_input_fingerprint != current_fingerprint
    ):
        reasons.append(COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED)
    return tuple(reasons)


def evaluate_comparison_assessment(
    comparable_result: ComparableResult,
    *,
    assessment_context: Mapping[str, Any] | None = None,
) -> ComparisonAssessment:
    context = _normalize_mapping(assessment_context)
    missing_critical_context = _derive_missing_critical_context(
        comparable_result,
        context,
    )
    comparability_basis = _derive_comparability_basis(comparable_result, context)
    comparability_warnings = _build_comparability_warnings(
        missing_critical_context=missing_critical_context,
        result_type=comparable_result.value.result_type,
        context_warnings=_derive_context_warnings(comparable_result, context),
    )
    comparability_status = _derive_comparability_status(
        missing_critical_context=missing_critical_context,
        traceability_status=comparable_result.evidence.traceability_status,
    )
    requires_expert_review = _requires_expert_review(
        comparability_status=comparability_status,
        result_type=comparable_result.value.result_type,
        missing_critical_context=missing_critical_context,
    )
    assessment_epistemic_status = _derive_assessment_epistemic_status(
        comparability_status=comparability_status,
        requires_expert_review=requires_expert_review,
    )
    return ComparisonAssessment(
        missing_critical_context=tuple(missing_critical_context),
        comparability_basis=tuple(comparability_basis),
        comparability_warnings=tuple(comparability_warnings),
        comparability_status=comparability_status,
        requires_expert_review=requires_expert_review,
        assessment_epistemic_status=assessment_epistemic_status,
    )


def _derive_missing_critical_context(
    comparable_result: ComparableResult,
    assessment_context: Mapping[str, Any],
) -> list[str]:
    missing: list[str] = []
    if not comparable_result.binding.variant_id:
        missing.append("variant_link")
    if not comparable_result.baseline_reference:
        missing.append("baseline_reference")
    if not comparable_result.binding.test_condition_id:
        missing.append("test_condition")
    if comparable_result.evidence.traceability_status != TRACEABILITY_STATUS_DIRECT:
        missing.append("direct_traceability")
    if not comparable_result.value.summary or comparable_result.value.summary == "Result reported":
        missing.append("result_value")
    if comparable_result.value.result_type not in SCALAR_LIKE_RESULT_TYPES:
        missing.append("expert_interpretation")
    if _is_pbf_context(comparable_result, assessment_context):
        _append_pbf_missing_context(missing, comparable_result, assessment_context)
    return missing


def _derive_comparability_basis(
    comparable_result: ComparableResult,
    assessment_context: Mapping[str, Any],
) -> list[str]:
    basis: list[str] = []
    if comparable_result.binding.variant_id:
        basis.append("variant_linked")
    if comparable_result.baseline_reference:
        basis.append("baseline_resolved")
    if comparable_result.binding.test_condition_id:
        basis.append("test_condition_resolved")
    if comparable_result.evidence.traceability_status == TRACEABILITY_STATUS_DIRECT:
        basis.append("direct_traceability")
    if comparable_result.value.numeric_value is not None:
        basis.append("numeric_value_available")
    if comparable_result.value.result_type in SCALAR_LIKE_RESULT_TYPES:
        basis.append(f"result_type:{comparable_result.value.result_type}")
    if comparable_result.evidence.structure_feature_ids:
        basis.append("structure_context_available")
    if comparable_result.evidence.characterization_observation_ids:
        basis.append("characterization_context_available")
    if _is_pbf_context(comparable_result, assessment_context):
        basis.append("pbf_context_detected")
        process_context = _process_context_from_assessment(assessment_context)
        condition_payload = _condition_payload_from_assessment(assessment_context)
        if _has_context_value(process_context.get("build_orientation")):
            basis.append("build_orientation_reported")
        if _has_context_value(_strain_rate_value(condition_payload)):
            basis.append("strain_rate_reported")
        if _has_context_value(condition_payload.get("loading_direction")):
            basis.append("loading_direction_reported")
        if _has_context_value(condition_payload.get("sample_orientation")):
            basis.append("sample_orientation_reported")
        energy_density_origin = _normalize_text(
            process_context.get("energy_density_origin")
        )
        if energy_density_origin:
            basis.append(f"energy_density_origin:{energy_density_origin}")
    return basis


def _build_comparability_warnings(
    *,
    missing_critical_context: list[str],
    result_type: str,
    context_warnings: list[str],
) -> list[str]:
    warnings: list[str] = []
    warning_map = {
        "variant_link": "Variant linkage could not be resolved for this result.",
        "baseline_reference": "Baseline reference is missing or unresolved.",
        "test_condition": "Test condition is missing or unresolved.",
        "direct_traceability": "Traceability is partial or indirect.",
        "result_value": "Result payload is incomplete for comparison display.",
        "expert_interpretation": "Result shape requires expert interpretation before comparison.",
        "build_orientation": "PBF build orientation is missing for an orientation-sensitive result.",
        "strain_rate_s-1": "Tensile-style PBF result is missing strain rate.",
        "loading_direction": "Tensile-style PBF result is missing loading direction.",
        "sample_orientation": "Tensile-style PBF result is missing sample orientation.",
        "energy_density_estimated": "Energy density is estimated and requires expert review before comparison.",
    }
    for item in missing_critical_context:
        warning = warning_map.get(item)
        if warning and warning not in warnings:
            warnings.append(warning)
    if result_type not in SCALAR_LIKE_RESULT_TYPES:
        warnings.append(
            "This comparison row summarizes a non-scalar result and should be reviewed by a domain expert."
        )
    for warning in context_warnings:
        if warning not in warnings:
            warnings.append(warning)
    return warnings


def _append_pbf_missing_context(
    missing: list[str],
    comparable_result: ComparableResult,
    assessment_context: Mapping[str, Any],
) -> None:
    process_context = _process_context_from_assessment(assessment_context)
    condition_payload = _condition_payload_from_assessment(assessment_context)
    property_name = _normalize_text(comparable_result.value.property_normalized) or ""

    if (
        property_name in PBF_ORIENTATION_SENSITIVE_PROPERTIES
        and not _has_context_value(process_context.get("build_orientation"))
    ):
        _append_once(missing, "build_orientation")

    if _is_tensile_style_result(comparable_result, condition_payload):
        if not _has_context_value(_strain_rate_value(condition_payload)):
            _append_once(missing, "strain_rate_s-1")
        if not _has_context_value(condition_payload.get("loading_direction")):
            _append_once(missing, "loading_direction")
        if not _has_context_value(condition_payload.get("sample_orientation")):
            _append_once(missing, "sample_orientation")

    if _normalize_text(process_context.get("energy_density_origin")) == "estimated":
        _append_once(missing, "energy_density_estimated")


def _derive_context_warnings(
    comparable_result: ComparableResult,
    assessment_context: Mapping[str, Any],
) -> list[str]:
    if not _is_pbf_context(comparable_result, assessment_context):
        return []

    warnings: list[str] = []
    process_context = _process_context_from_assessment(assessment_context)
    energy_density_origin = _normalize_text(process_context.get("energy_density_origin"))
    if energy_density_origin == "derived":
        warnings.append(
            "Energy density was derived from reported inputs; verify the formula before cross-paper comparison."
        )
    post_treatment = (_normalize_text(process_context.get("post_treatment_summary")) or "").lower()
    if any(token in post_treatment for token in ("mixed", "multiple", "varied")):
        warnings.append(
            "Post-treatment state appears mixed under one variant and should be reviewed."
        )
    return warnings


def _is_pbf_context(
    comparable_result: ComparableResult,
    assessment_context: Mapping[str, Any],
) -> bool:
    variant = _normalize_mapping(assessment_context.get("variant"))
    if _normalize_text(variant.get("domain_profile")) == "pbf_metal":
        return True

    process_context = _process_context_from_assessment(assessment_context)
    if any(
        _has_context_value(process_context.get(key))
        for key in PBF_PROCESS_CONTEXT_KEYS
    ):
        return True

    process_text = (
        comparable_result.normalized_context.process_normalized or ""
    ).lower()
    return any(
        token in process_text
        for token in (
            "lpbf",
            "pbf-lb",
            "powder bed fusion",
            "laser powder bed",
            "slm",
        )
    )


def _is_tensile_style_result(
    comparable_result: ComparableResult,
    condition_payload: Mapping[str, Any],
) -> bool:
    property_name = _normalize_text(comparable_result.value.property_normalized) or ""
    if property_name in PBF_TENSILE_STYLE_PROPERTIES:
        return True
    method_text = " ".join(
        str(item)
        for item in (
            condition_payload.get("test_method"),
            condition_payload.get("method"),
            *_normalize_string_tuple(condition_payload.get("methods")),
        )
        if _normalize_text(item)
    ).lower()
    return "tensile" in method_text or "strain" in method_text


def _process_context_from_assessment(
    assessment_context: Mapping[str, Any],
) -> Mapping[str, Any]:
    variant = _normalize_mapping(assessment_context.get("variant"))
    return _normalize_mapping(variant.get("process_context"))


def _condition_payload_from_assessment(
    assessment_context: Mapping[str, Any],
) -> Mapping[str, Any]:
    condition = _normalize_mapping(assessment_context.get("test_condition"))
    return _normalize_mapping(condition.get("condition_payload"))


def _strain_rate_value(condition_payload: Mapping[str, Any]) -> Any:
    return (
        condition_payload.get("strain_rate_s-1")
        or condition_payload.get("strain_rate_s_1")
        or condition_payload.get("strain_rate")
        or condition_payload.get("rate")
    )


def _has_context_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(str(value).strip())


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _derive_comparability_status(
    *,
    missing_critical_context: list[str],
    traceability_status: str,
) -> str:
    missing = set(missing_critical_context)
    if traceability_status == TRACEABILITY_STATUS_MISSING:
        return COMPARABILITY_STATUS_INSUFFICIENT
    if {"baseline_reference", "test_condition"} <= missing:
        return COMPARABILITY_STATUS_NOT_COMPARABLE
    if "variant_link" in missing and {"baseline_reference", "test_condition"} & missing:
        return COMPARABILITY_STATUS_INSUFFICIENT
    if missing:
        return COMPARABILITY_STATUS_LIMITED
    return COMPARABILITY_STATUS_COMPARABLE


def _requires_expert_review(
    *,
    comparability_status: str,
    result_type: str,
    missing_critical_context: list[str],
) -> bool:
    if comparability_status != COMPARABILITY_STATUS_COMPARABLE:
        return True
    if result_type not in SCALAR_LIKE_RESULT_TYPES:
        return True
    return bool(missing_critical_context)


def _derive_assessment_epistemic_status(
    *,
    comparability_status: str,
    requires_expert_review: bool,
) -> str:
    if comparability_status == COMPARABILITY_STATUS_COMPARABLE and not requires_expert_review:
        return EPISTEMIC_NORMALIZED_FROM_EVIDENCE
    if comparability_status == COMPARABILITY_STATUS_LIMITED:
        return EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE
    return EPISTEMIC_UNRESOLVED


def _build_deterministic_id(prefix: str, payload: Mapping[str, Any]) -> str:
    canonical = _canonicalize_for_identity(payload)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{prefix}_{sha1(encoded).hexdigest()[:16]}"


def _canonicalize_for_identity(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray, dict)):
        value = value.tolist()
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize_for_identity(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, set):
        return sorted(
            (_canonicalize_for_identity(item) for item in value),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    if isinstance(value, (list, tuple)):
        return [_canonicalize_for_identity(item) for item in value]
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return int(value)
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    text = _normalize_text(value)
    return text


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _normalize_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if _normalize_text(item)]
        return tuple(items)
    text = _normalize_text(value)
    return (text,) if text else ()


def _normalize_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return bool(value)


def _normalize_optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_scalar_or_text(value: Any) -> str | float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return int(value)
        return value
    text = _normalize_text(value)
    return text


def _normalize_optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                return {}
            if isinstance(parsed, Mapping):
                return parsed
    return {}


__all__ = [
    "COMPARABLE_RESULT_NORMALIZATION_VERSION",
    "COMPARISON_ROW_PROJECTION_VERSION",
    "COLLECTION_COMPARISON_POLICY_FAMILY",
    "COLLECTION_COMPARISON_POLICY_VERSION",
    "COLLECTION_REASSESSMENT_TRIGGER_ASSESSMENT_INPUT_CHANGED",
    "COLLECTION_REASSESSMENT_TRIGGER_NORMALIZATION_VERSION_CHANGED",
    "COLLECTION_REASSESSMENT_TRIGGER_POLICY_FAMILY_CHANGED",
    "COLLECTION_REASSESSMENT_TRIGGER_POLICY_VERSION_CHANGED",
    "DEFAULT_COLLECTION_REASSESSMENT_TRIGGERS",
    "CollectionComparableResult",
    "ComparableResult",
    "ComparisonAssessment",
    "ComparisonAxis",
    "ComparisonRowRecord",
    "ContextBinding",
    "EvidenceTrace",
    "NormalizedComparisonContext",
    "ResultValue",
    "SCALAR_LIKE_RESULT_TYPES",
    "build_collection_assessment_input_fingerprint",
    "build_comparable_result_id",
    "build_comparison_row_id",
    "evaluate_collection_reassessment_reasons",
    "evaluate_comparison_assessment",
]
