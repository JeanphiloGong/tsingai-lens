from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.core.comparison import ComparisonRowRecord
from domain.core.evidence_backbone import (
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    SampleVariant,
)
from domain.core.fact_store import CoreFactSet
from domain.core.paper_fact import PaperFactSet
from domain.shared.enums import TRACEABILITY_STATUS_DIRECT, TRACEABILITY_STATUS_MISSING


@dataclass(frozen=True)
class CoreFactProjectionRecords:
    document_profiles: tuple[dict[str, Any], ...]
    evidence_cards: tuple[dict[str, Any], ...]
    comparison_rows: tuple[dict[str, Any], ...]


def build_core_fact_projection_records(
    paper_facts: PaperFactSet,
    core_facts: CoreFactSet,
) -> CoreFactProjectionRecords:
    return CoreFactProjectionRecords(
        document_profiles=tuple(
            profile.to_record() for profile in paper_facts.document_profiles
        ),
        evidence_cards=tuple(_build_evidence_card_records(paper_facts, core_facts)),
        comparison_rows=tuple(row.to_record() for row in core_facts.comparison_rows),
    )


def _build_evidence_card_records(
    paper_facts: PaperFactSet,
    core_facts: CoreFactSet,
) -> list[dict[str, Any]]:
    anchor_lookup = {
        anchor.anchor_id: anchor
        for anchor in paper_facts.evidence_anchors
        if anchor.anchor_id
    }
    variant_lookup = {
        variant.variant_id: variant
        for variant in paper_facts.sample_variants
        if variant.variant_id
    }
    document_material_lookup: dict[str, dict[str, Any]] = {}
    for variant in paper_facts.sample_variants:
        if not variant.document_id or variant.document_id in document_material_lookup:
            continue
        document_material_lookup[variant.document_id] = dict(variant.host_material_system)

    records: dict[str, dict[str, Any]] = {}
    for method in paper_facts.method_facts:
        evidence_id = _method_fact_evidence_id(method)
        if not evidence_id:
            continue
        anchors = _anchor_records(method.evidence_anchor_ids, anchor_lookup)
        records[evidence_id] = {
            "evidence_id": evidence_id,
            "document_id": method.document_id,
            "collection_id": method.collection_id,
            "claim_text": _method_claim_text(method),
            "claim_type": _method_claim_type(method),
            "evidence_source_type": _evidence_source_type(anchors, "method"),
            "evidence_anchors": anchors,
            "material_system": document_material_lookup.get(method.document_id, {}),
            "condition_context": {
                "method_role": method.method_role,
                "method_name": method.method_name,
                "method_payload": dict(method.method_payload),
            },
            "confidence": method.confidence,
            "traceability_status": (
                TRACEABILITY_STATUS_DIRECT if anchors else TRACEABILITY_STATUS_MISSING
            ),
        }

    for result in paper_facts.measurement_results:
        evidence_id = _measurement_result_evidence_id(result)
        if not evidence_id:
            continue
        variant = variant_lookup.get(result.variant_id or "")
        anchors = _anchor_records(result.evidence_anchor_ids, anchor_lookup)
        records[evidence_id] = {
            "evidence_id": evidence_id,
            "document_id": result.document_id,
            "collection_id": result.collection_id,
            "claim_text": _measurement_claim_text(result, variant),
            "claim_type": "property",
            "evidence_source_type": _evidence_source_type(
                anchors,
                result.result_source_type or "text",
            ),
            "evidence_anchors": anchors,
            "material_system": dict(variant.host_material_system) if variant else {},
            "condition_context": {
                "test_condition_id": result.test_condition_id,
                "baseline_id": result.baseline_id,
            },
            "confidence": 0.0,
            "traceability_status": result.traceability_status or TRACEABILITY_STATUS_MISSING,
        }

    for row in core_facts.comparison_rows:
        for evidence_id in row.supporting_evidence_ids:
            if not evidence_id or evidence_id in records:
                continue
            anchors = _anchor_records(row.supporting_anchor_ids, anchor_lookup)
            records[evidence_id] = _fallback_evidence_card_record(row, evidence_id, anchors)

    return list(records.values())


def _anchor_records(
    anchor_ids: tuple[str, ...],
    anchor_lookup: dict[str, EvidenceAnchor],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for anchor_id in anchor_ids:
        anchor = anchor_lookup.get(anchor_id)
        if anchor is not None:
            records.append(anchor.to_record())
    return records


def _method_fact_evidence_id(method: MethodFact) -> str:
    return f"ev_method_{method.method_id or 'missing'}"


def _measurement_result_evidence_id(result: MeasurementResult) -> str:
    return f"ev_result_{result.result_id or 'missing'}"


def _method_claim_text(method: MethodFact) -> str:
    details = _text(method.method_payload.get("details"))
    if details:
        return details
    method_name = method.method_name or "unspecified method"
    if method.method_role == "characterization":
        return f"Characterization used {method_name}."
    if method.method_role == "test":
        return f"Testing used {method_name}."
    return f"Process used {method_name}."


def _method_claim_type(method: MethodFact) -> str:
    if method.method_role == "process":
        return "process"
    if method.method_role == "characterization":
        return "characterization"
    return "qualitative"


def _measurement_claim_text(
    result: MeasurementResult,
    variant: SampleVariant | None,
) -> str:
    for key in ("statement", "source_value_text", "summary"):
        text = _text(result.value_payload.get(key))
        if text:
            return text
    value = result.value_payload.get("value")
    variant_label = variant.variant_label if variant and variant.variant_label else "sample"
    property_name = result.property_normalized or "property"
    if value is not None and _text(value):
        unit = f" {result.unit}" if result.unit else ""
        return f"{variant_label} reported {property_name} of {_text(value)}{unit}."
    return f"{variant_label} reported {property_name}."


def _fallback_evidence_card_record(
    row: ComparisonRowRecord,
    evidence_id: str,
    anchors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "document_id": row.source_document_id,
        "collection_id": row.collection_id,
        "claim_text": row.result_summary or evidence_id,
        "claim_type": "property",
        "evidence_source_type": _evidence_source_type(anchors, row.result_source_type or "text"),
        "evidence_anchors": anchors,
        "material_system": {"normalized": row.material_system_normalized},
        "condition_context": {
            "process": row.process_normalized,
            "baseline": row.baseline_normalized,
            "test": row.test_condition_normalized,
        },
        "confidence": 0.0,
        "traceability_status": (
            TRACEABILITY_STATUS_DIRECT if anchors else TRACEABILITY_STATUS_MISSING
        ),
    }


def _evidence_source_type(anchors: list[dict[str, Any]], fallback: str) -> str:
    for anchor in anchors:
        source_type = _text(anchor.get("source_type"))
        if source_type:
            return source_type
    return fallback or "text"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "CoreFactProjectionRecords",
    "build_core_fact_projection_records",
]
