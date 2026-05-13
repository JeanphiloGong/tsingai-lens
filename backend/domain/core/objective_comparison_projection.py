from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from domain.core.comparison import (
    COMPARISON_ROW_PROJECTION_VERSION,
    ComparisonRowRecord,
    build_comparison_row_id,
)
from domain.core.research_objective import ObjectiveEvidenceUnit
from domain.shared.enums import (
    COMPARABILITY_STATUS_COMPARABLE,
    COMPARABILITY_STATUS_LIMITED,
    EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE,
    EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
)


_SKIPPED_RESOLUTION_STATUSES = {"rejected", "skipped"}


def project_objective_comparison_rows(
    *,
    collection_id: str,
    evidence_units: Iterable[ObjectiveEvidenceUnit],
) -> tuple[ComparisonRowRecord, ...]:
    rows = [
        _row_from_measurement_unit(collection_id, unit)
        for unit in evidence_units
        if _is_projectable_measurement(unit)
    ]
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.source_document_id,
                row.property_normalized,
                row.variant_label or "",
                row.comparable_result_id,
            ),
        )
    )


def _is_projectable_measurement(unit: ObjectiveEvidenceUnit) -> bool:
    return (
        unit.unit_kind == "measurement"
        and unit.resolution_status not in _SKIPPED_RESOLUTION_STATUSES
    )


def _row_from_measurement_unit(
    collection_id: str,
    unit: ObjectiveEvidenceUnit,
) -> ComparisonRowRecord:
    material = _material_label(unit.material_system)
    sample_label = _sample_label(unit.sample_context)
    property_name = _safe_text(unit.property_normalized)
    test_condition = _condition_label(unit.test_condition) or _condition_label(
        unit.resolved_condition
    )
    value = _numeric_value(unit.value_payload)
    display_value = _value_display(unit.value_payload, unit.unit)
    missing = _missing_context(
        material=material,
        sample_label=sample_label,
        property_name=property_name,
        test_condition=test_condition,
        display_value=display_value,
    )
    comparability_status = (
        COMPARABILITY_STATUS_COMPARABLE
        if not missing
        else COMPARABILITY_STATUS_LIMITED
    )
    comparable_result_id = f"objective:{unit.evidence_unit_id}"
    return ComparisonRowRecord(
        row_id=build_comparison_row_id(
            collection_id=collection_id,
            comparable_result_id=comparable_result_id,
            projection_version=COMPARISON_ROW_PROJECTION_VERSION,
        ),
        collection_id=collection_id,
        comparable_result_id=comparable_result_id,
        source_document_id=unit.document_id,
        variant_id=_sample_key(unit.document_id, sample_label),
        variant_label=sample_label,
        variable_axis=_safe_text(unit.value_payload.get("comparison_axis")),
        variable_value=_safe_text(unit.value_payload.get("comparison_axis_value")),
        baseline_reference=_baseline_label(unit.baseline_context),
        result_source_type=_source_kind(unit.source_refs),
        result_type="scalar" if value is not None else "qualitative",
        result_summary=display_value or "Result reported",
        supporting_evidence_ids=(unit.evidence_unit_id,),
        supporting_anchor_ids=tuple(unit.evidence_anchor_ids),
        characterization_observation_ids=(),
        structure_feature_ids=(),
        material_system_normalized=material or "unspecified material system",
        process_normalized=_process_label(unit.process_context)
        or "unspecified process",
        property_normalized=property_name or "qualitative",
        baseline_normalized=_baseline_label(unit.baseline_context)
        or "unspecified baseline",
        test_condition_normalized=test_condition or "unspecified test condition",
        comparability_status=comparability_status,
        comparability_warnings=tuple(
            f"missing {field}" for field in missing
        ),
        comparability_basis=(
            "projected_from_objective_evidence_unit",
            f"resolution_status={unit.resolution_status}",
        ),
        requires_expert_review=bool(missing),
        assessment_epistemic_status=(
            EPISTEMIC_NORMALIZED_FROM_EVIDENCE
            if not missing
            else EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE
        ),
        missing_critical_context=tuple(missing),
        value=value,
        unit=unit.unit,
    )


def _missing_context(
    *,
    material: str | None,
    sample_label: str | None,
    property_name: str | None,
    test_condition: str | None,
    display_value: str | None,
) -> list[str]:
    missing: list[str] = []
    if not material:
        missing.append("material_system")
    if not sample_label:
        missing.append("sample_context")
    if not property_name:
        missing.append("property")
    if not test_condition:
        missing.append("test_condition")
    if not display_value:
        missing.append("value")
    return missing


def _material_label(material_system: Mapping[str, Any]) -> str | None:
    return _first_text(
        material_system,
        (
            "name",
            "material_system",
            "material",
            "host_material_system",
            "family",
            "composition",
            "alloy",
        ),
    )


def _sample_label(sample_context: Mapping[str, Any]) -> str | None:
    return _first_text(
        sample_context,
        (
            "sample",
            "sample_label",
            "variant_label",
            "sample_name",
            "specimen",
            "condition",
            "sample_id",
        ),
    )


def _sample_key(document_id: str, sample_label: str | None) -> str | None:
    if not sample_label:
        return None
    return f"{document_id}:{_slug(sample_label)}"


def _process_label(process_context: Mapping[str, Any]) -> str | None:
    return _first_text(
        process_context,
        (
            "process_normalized",
            "process_family",
            "process",
            "manufacturing_process",
            "process_name",
            "post_treatment_summary",
        ),
    )


def _condition_label(condition: Mapping[str, Any]) -> str | None:
    values = [
        f"{key}: {value}"
        for key, value in condition.items()
        if _safe_text(value)
    ]
    return "; ".join(values) if values else None


def _baseline_label(baseline_context: Mapping[str, Any]) -> str | None:
    direct = _first_text(
        baseline_context,
        ("baseline", "baseline_label", "label", "sample", "sample_label"),
    )
    if direct:
        return direct
    nested = baseline_context.get("sample_context")
    if isinstance(nested, Mapping):
        return _sample_label(nested)
    return None


def _source_kind(source_refs: tuple[dict[str, Any], ...]) -> str:
    if not source_refs:
        return "objective_unit"
    return _safe_text(source_refs[0].get("source_kind")) or "objective_unit"


def _numeric_value(value_payload: Mapping[str, Any]) -> float | None:
    for key in ("value", "normalized_value", "current_value"):
        value = value_payload.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _value_display(
    value_payload: Mapping[str, Any],
    unit: str | None,
) -> str | None:
    display = _safe_text(value_payload.get("source_value_text"))
    if not display:
        value = _numeric_value(value_payload)
        display = f"{value:g}" if value is not None else None
    if display and unit and unit not in display:
        return f"{display} {unit}"
    return display


def _first_text(
    payload: Mapping[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        if value := _safe_text(payload.get(key)):
            return value
    return None


def _safe_text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "n/a", "na"}:
        return None
    return text


def _slug(value: str) -> str:
    return "-".join(value.strip().lower().split()) or "unspecified"


__all__ = ["project_objective_comparison_rows"]
