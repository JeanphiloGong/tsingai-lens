from __future__ import annotations

from domain.core import ObjectiveEvidenceUnit, project_objective_material_rows


def test_project_objective_material_rows_preserves_unit_contexts():
    measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-measurement-1",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "as-built"},
            "process_context": {"process": "LPBF"},
            "resolved_condition": {"medium": "3.5 wt.% NaCl"},
            "test_condition": {"method": "potentiodynamic polarization"},
            "property_normalized": "corrosion current density",
            "value_payload": {"value": 1.2, "source_value_text": "1.2 uA/cm2"},
            "unit": "uA/cm2",
            "baseline_context": {"baseline": "heat-treated"},
            "source_refs": [{"route_id": "route-table-1", "source_ref": "table-1"}],
            "evidence_anchor_ids": ["anc-1"],
            "resolution_status": "resolved",
            "confidence": 0.86,
        }
    )
    process_context = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-process-1",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "process_context",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "heat-treated"},
            "process_context": {"post_treatment_summary": "annealed at 1050 C"},
            "source_refs": [{"route_id": "route-text-1", "source_ref": "b2"}],
            "resolution_status": "partial",
            "confidence": 0.72,
        }
    )
    skipped = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-skipped",
            "objective_id": "obj-corrosion",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "ignored"},
            "property_normalized": "corrosion potential",
            "value_payload": {"value": -0.4},
            "resolution_status": "skipped",
        }
    )
    contaminated_text_measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-text-ductility",
            "objective_id": "obj-mechanical",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"sample": "135 W-750 mm·s -1"},
            "property_normalized": "elongation",
            "value_payload": {
                "source_value_text": (
                    "The relatively low porosity levels in the 135 W-750 "
                    "mm·s -1 sample increase the ductility by about 10%."
                )
            },
            "source_refs": [{"source_kind": "text_window", "source_ref": "blk-1"}],
            "resolution_status": "partial",
        }
    )

    rows = project_objective_material_rows(
        (measurement, process_context, skipped, contaminated_text_measurement)
    )

    assert [row.evidence_unit_id for row in rows] == [
        "oeu-measurement-1",
        "oeu-process-1",
    ]
    assert rows[0].material_system == {"name": "316L stainless steel"}
    assert rows[0].sample_context == {"sample": "as-built"}
    assert rows[0].process_context == {"process": "LPBF"}
    assert rows[0].resolved_condition == {"medium": "3.5 wt.% NaCl"}
    assert rows[0].test_condition == {"method": "potentiodynamic polarization"}
    assert rows[0].property_normalized == "corrosion current density"
    assert rows[0].value_payload == {
        "value": 1.2,
        "source_value_text": "1.2 uA/cm2",
    }
    assert rows[0].source_refs == (
        {"route_id": "route-table-1", "source_ref": "table-1"},
    )
    assert rows[0].evidence_anchor_ids == ("anc-1",)
    assert rows[1].resolution_status == "partial"
