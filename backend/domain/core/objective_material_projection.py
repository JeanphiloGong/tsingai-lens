from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from domain.core.research_objective import ObjectiveEvidenceUnit


_SKIPPED_RESOLUTION_STATUSES = {"rejected", "skipped"}


@dataclass(frozen=True)
class ObjectiveMaterialProjectionRow:
    evidence_unit_id: str
    objective_id: str
    document_id: str
    unit_kind: str
    material_system: dict[str, Any]
    sample_context: dict[str, Any]
    process_context: dict[str, Any]
    resolved_condition: dict[str, Any]
    test_condition: dict[str, Any]
    property_normalized: str | None
    value_payload: dict[str, Any]
    unit: str | None
    baseline_context: dict[str, Any]
    source_refs: tuple[dict[str, Any], ...]
    evidence_anchor_ids: tuple[str, ...]
    resolution_status: str
    confidence: float

    @classmethod
    def from_evidence_unit(
        cls,
        unit: ObjectiveEvidenceUnit,
    ) -> "ObjectiveMaterialProjectionRow":
        return cls(
            evidence_unit_id=unit.evidence_unit_id,
            objective_id=unit.objective_id,
            document_id=unit.document_id,
            unit_kind=unit.unit_kind,
            material_system=dict(unit.material_system),
            sample_context=dict(unit.sample_context),
            process_context=dict(unit.process_context),
            resolved_condition=dict(unit.resolved_condition),
            test_condition=dict(unit.test_condition),
            property_normalized=unit.property_normalized,
            value_payload=dict(unit.value_payload),
            unit=unit.unit,
            baseline_context=dict(unit.baseline_context),
            source_refs=tuple(dict(ref) for ref in unit.source_refs),
            evidence_anchor_ids=tuple(unit.evidence_anchor_ids),
            resolution_status=unit.resolution_status,
            confidence=unit.confidence,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "evidence_unit_id": self.evidence_unit_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "unit_kind": self.unit_kind,
            "material_system": dict(self.material_system),
            "sample_context": dict(self.sample_context),
            "process_context": dict(self.process_context),
            "resolved_condition": dict(self.resolved_condition),
            "test_condition": dict(self.test_condition),
            "property_normalized": self.property_normalized,
            "value_payload": dict(self.value_payload),
            "unit": self.unit,
            "baseline_context": dict(self.baseline_context),
            "source_refs": [dict(ref) for ref in self.source_refs],
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "resolution_status": self.resolution_status,
            "confidence": self.confidence,
        }


def project_objective_material_rows(
    evidence_units: Iterable[ObjectiveEvidenceUnit],
) -> tuple[ObjectiveMaterialProjectionRow, ...]:
    rows: list[ObjectiveMaterialProjectionRow] = []
    for unit in evidence_units:
        if unit.resolution_status in _SKIPPED_RESOLUTION_STATUSES:
            continue
        if not _has_material_projection_payload(unit):
            continue
        rows.append(ObjectiveMaterialProjectionRow.from_evidence_unit(unit))
    return tuple(rows)


def _has_material_projection_payload(unit: ObjectiveEvidenceUnit) -> bool:
    return any(
        (
            unit.material_system,
            unit.sample_context,
            unit.process_context,
            unit.resolved_condition,
            unit.test_condition,
            unit.property_normalized,
            unit.value_payload,
        )
    )
