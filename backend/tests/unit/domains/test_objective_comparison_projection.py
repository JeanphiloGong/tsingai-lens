from __future__ import annotations

from domain.core import (
    ObjectiveEvidenceUnit,
    project_objective_comparison_rows,
    project_objective_comparison_semantics,
)


def test_project_objective_comparison_rows_from_measurement_units():
    rows = project_objective_comparison_rows(
        collection_id="col-1",
        evidence_units=(
            ObjectiveEvidenceUnit.from_mapping(
                {
                    "evidence_unit_id": "oeu-as-built-icorr",
                    "objective_id": "obj-corrosion",
                    "document_id": "paper-1",
                    "unit_kind": "measurement",
                    "material_system": {"name": "316L stainless steel"},
                    "sample_context": {"sample": "as-built"},
                    "process_context": {"process": "LPBF"},
                    "resolved_condition": {"medium": "3.5 wt.% NaCl"},
                    "test_condition": {"method": "polarization"},
                    "property_normalized": "corrosion current density",
                    "value_payload": {
                        "value": 1.2,
                        "source_value_text": "1.2 uA/cm2",
                    },
                    "unit": "uA/cm2",
                    "source_refs": [{"source_kind": "table", "source_ref": "table-1"}],
                    "evidence_anchor_ids": ["anc-1"],
                    "resolution_status": "resolved",
                    "confidence": 0.9,
                }
            ),
            ObjectiveEvidenceUnit.from_mapping(
                {
                    "evidence_unit_id": "oeu-skipped",
                    "objective_id": "obj-corrosion",
                    "document_id": "paper-1",
                    "unit_kind": "measurement",
                    "material_system": {"name": "316L stainless steel"},
                    "property_normalized": "corrosion potential",
                    "value_payload": {"value": -0.4},
                    "resolution_status": "skipped",
                }
            ),
            ObjectiveEvidenceUnit.from_mapping(
                {
                    "evidence_unit_id": "oeu-candidate",
                    "objective_id": "obj-corrosion",
                    "document_id": "paper-1",
                    "selection_status": "candidate",
                    "unit_kind": "measurement",
                    "property_normalized": "pitting potential",
                    "value_payload": {"value": 0.2},
                    "resolution_status": "resolved",
                }
            ),
        ),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.collection_id == "col-1"
    assert row.comparable_result_id == "objective:oeu-as-built-icorr"
    assert row.source_document_id == "paper-1"
    assert row.variant_label == "as-built"
    assert row.material_system_normalized == "316L stainless steel"
    assert row.process_normalized == "LPBF"
    assert row.property_normalized == "corrosion current density"
    assert row.test_condition_normalized == "method: polarization"
    assert row.result_source_type == "table"
    assert row.result_summary == "1.2 uA/cm2"
    assert row.supporting_evidence_ids == ("oeu-as-built-icorr",)
    assert row.supporting_anchor_ids == ("anc-1",)
    assert row.value == 1.2
    assert row.unit == "uA/cm2"
    assert row.missing_critical_context == ()

    semantics = project_objective_comparison_semantics(
        collection_id="col-1",
        evidence_units=(
            ObjectiveEvidenceUnit.from_mapping(
                {
                    "evidence_unit_id": "oeu-as-built-icorr",
                    "objective_id": "obj-corrosion",
                    "document_id": "paper-1",
                    "unit_kind": "measurement",
                    "material_system": {"name": "316L stainless steel"},
                    "sample_context": {"sample": "as-built"},
                    "process_context": {"process": "LPBF"},
                    "test_condition": {"method": "polarization"},
                    "property_normalized": "corrosion current density",
                    "value_payload": {
                        "value": 1.2,
                        "source_value_text": "1.2 uA/cm2",
                    },
                    "unit": "uA/cm2",
                    "source_refs": [{"source_kind": "table", "source_ref": "table-1"}],
                    "evidence_anchor_ids": ["anc-1"],
                    "resolution_status": "resolved",
                }
            ),
        ),
    )
    assert len(semantics.comparable_results) == 1
    assert len(semantics.collection_comparable_results) == 1
    assert semantics.comparable_results[0].source_result_id == "oeu-as-built-icorr"
    assert (
        semantics.collection_comparable_results[0].comparable_result_id
        == "objective:oeu-as-built-icorr"
    )


def test_project_objective_comparison_rows_marks_missing_context():
    rows = project_objective_comparison_rows(
        collection_id="col-1",
        evidence_units=(
            ObjectiveEvidenceUnit.from_mapping(
                {
                    "evidence_unit_id": "oeu-incomplete",
                    "objective_id": "obj-corrosion",
                    "document_id": "paper-1",
                    "unit_kind": "measurement",
                    "value_payload": {"value": 1.2},
                    "resolution_status": "partial",
                }
            ),
        ),
    )

    row = rows[0]
    assert row.comparability_status == "limited"
    assert set(row.missing_critical_context) == {
        "material_system",
        "sample_context",
        "property",
        "test_condition",
    }
    assert row.requires_expert_review is True


def test_project_objective_comparison_rows_skips_text_measurement_without_explicit_value():
    rows = project_objective_comparison_rows(
        collection_id="col-1",
        evidence_units=(
            ObjectiveEvidenceUnit.from_mapping(
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
                    "source_refs": [
                        {"source_kind": "text_window", "source_ref": "blk-1"}
                    ],
                    "resolution_status": "partial",
                }
            ),
        ),
    )

    assert rows == ()
