from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ComparisonAssessment:
    missing_critical_context: tuple[str, ...]
    comparability_basis: tuple[str, ...]
    comparability_warnings: tuple[str, ...]
    comparability_status: str
    requires_expert_review: bool
    assessment_epistemic_status: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "missing_critical_context": list(self.missing_critical_context),
            "comparability_basis": list(self.comparability_basis),
            "comparability_warnings": list(self.comparability_warnings),
            "comparability_status": self.comparability_status,
            "requires_expert_review": self.requires_expert_review,
            "assessment_epistemic_status": self.assessment_epistemic_status,
        }


@dataclass(frozen=True)
class ComparisonRow:
    row_id: str
    collection_id: str
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
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ComparisonRow":
        return cls(
            row_id=_normalize_text(payload.get("row_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
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


def evaluate_comparison_assessment(
    *,
    variant_id: str | None,
    baseline_reference: str | None,
    test_condition_id: str | None,
    traceability_status: str,
    result_type: str,
    result_summary: str,
    numeric_value: float | None,
    structure_feature_ids: list[str],
    characterization_observation_ids: list[str],
) -> ComparisonAssessment:
    missing_critical_context = _derive_missing_critical_context(
        variant_id=variant_id,
        baseline_reference=baseline_reference,
        test_condition_id=test_condition_id,
        traceability_status=traceability_status,
        result_type=result_type,
        result_summary=result_summary,
    )
    comparability_basis = _derive_comparability_basis(
        variant_id=variant_id,
        baseline_reference=baseline_reference,
        test_condition_id=test_condition_id,
        traceability_status=traceability_status,
        result_type=result_type,
        numeric_value=numeric_value,
        structure_feature_ids=structure_feature_ids,
        characterization_observation_ids=characterization_observation_ids,
    )
    comparability_warnings = _build_comparability_warnings(
        missing_critical_context=missing_critical_context,
        result_type=result_type,
    )
    comparability_status = _derive_comparability_status(
        missing_critical_context=missing_critical_context,
        traceability_status=traceability_status,
    )
    requires_expert_review = _requires_expert_review(
        comparability_status=comparability_status,
        result_type=result_type,
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
    *,
    variant_id: str | None,
    baseline_reference: str | None,
    test_condition_id: str | None,
    traceability_status: str,
    result_type: str,
    result_summary: str,
) -> list[str]:
    missing: list[str] = []
    if not variant_id:
        missing.append("variant_link")
    if not baseline_reference:
        missing.append("baseline_reference")
    if not test_condition_id:
        missing.append("test_condition")
    if traceability_status != TRACEABILITY_STATUS_DIRECT:
        missing.append("direct_traceability")
    if not result_summary or result_summary == "Result reported":
        missing.append("result_value")
    if result_type not in SCALAR_LIKE_RESULT_TYPES:
        missing.append("expert_interpretation")
    return missing


def _derive_comparability_basis(
    *,
    variant_id: str | None,
    baseline_reference: str | None,
    test_condition_id: str | None,
    traceability_status: str,
    result_type: str,
    numeric_value: float | None,
    structure_feature_ids: list[str],
    characterization_observation_ids: list[str],
) -> list[str]:
    basis: list[str] = []
    if variant_id:
        basis.append("variant_linked")
    if baseline_reference:
        basis.append("baseline_resolved")
    if test_condition_id:
        basis.append("test_condition_resolved")
    if traceability_status == TRACEABILITY_STATUS_DIRECT:
        basis.append("direct_traceability")
    if numeric_value is not None:
        basis.append("numeric_value_available")
    if result_type in SCALAR_LIKE_RESULT_TYPES:
        basis.append(f"result_type:{result_type}")
    if structure_feature_ids:
        basis.append("structure_context_available")
    if characterization_observation_ids:
        basis.append("characterization_context_available")
    return basis


def _build_comparability_warnings(
    *,
    missing_critical_context: list[str],
    result_type: str,
) -> list[str]:
    warnings: list[str] = []
    warning_map = {
        "variant_link": "Variant linkage could not be resolved for this result.",
        "baseline_reference": "Baseline reference is missing or unresolved.",
        "test_condition": "Test condition is missing or unresolved.",
        "direct_traceability": "Traceability is partial or indirect.",
        "result_value": "Result payload is incomplete for comparison display.",
        "expert_interpretation": "Result shape requires expert interpretation before comparison.",
    }
    for item in missing_critical_context:
        warning = warning_map.get(item)
        if warning and warning not in warnings:
            warnings.append(warning)
    if result_type not in SCALAR_LIKE_RESULT_TYPES:
        warnings.append(
            "This comparison row summarizes a non-scalar result and should be reviewed by a domain expert."
        )
    return warnings


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
    if (
        comparability_status == COMPARABILITY_STATUS_COMPARABLE
        and not requires_expert_review
    ):
        return EPISTEMIC_NORMALIZED_FROM_EVIDENCE
    if comparability_status == COMPARABILITY_STATUS_LIMITED:
        return EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE
    return EPISTEMIC_UNRESOLVED


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


__all__ = [
    "ComparisonAssessment",
    "ComparisonRow",
    "SCALAR_LIKE_RESULT_TYPES",
    "evaluate_comparison_assessment",
]
