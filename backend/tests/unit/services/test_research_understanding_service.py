from __future__ import annotations

from application.core.research_understanding_service import (
    ResearchUnderstandingService,
)
from domain.core import ResearchUnderstanding


def test_objective_understanding_projects_claims_relations_and_evidence_refs():
    service = ResearchUnderstandingService()
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-corrosion",
            "question": "How does heat treatment affect corrosion resistance?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["corrosion resistance"],
        },
        "objective_context": {
            "objective_id": "obj-corrosion",
            "question": "How does heat treatment affect corrosion resistance?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["heat treatment"],
            "target_property_axes": ["corrosion resistance"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-corrosion",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "corrosion current density",
                "value_payload": {"source_value_text": "0.4 uA/cm2"},
                "unit": "uA/cm2",
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-1",
                        "display_label": "P001 Table 1",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.91,
            },
            {
                "evidence_unit_id": "oeu-comparison",
                "document_id": "paper-1",
                "unit_kind": "comparison",
                "property_normalized": "corrosion resistance",
                "sample_context": {"sample": "heat-treated"},
                "baseline_context": {"sample": "as-built"},
                "value_payload": {
                    "comparison_axis": "heat treatment",
                    "direction": "improves",
                    "source_value_text": "heat treatment improves corrosion response",
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-1",
                        "display_label": "P001 Table 1",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.82,
            },
        ],
        "logic_chain": {
            "evidence_unit_ids": ["oeu-corrosion", "oeu-comparison"],
            "summary": "Heat treatment improves the corrosion response.",
        },
    }

    understanding = service.build_objective_understanding(payload)

    ResearchUnderstanding.from_mapping(understanding)
    assert understanding["schema_version"] == "research_understanding.v1"
    assert understanding["state"] == "ready"
    assert understanding["scope"]["scope_type"] == "objective"
    assert understanding["scope"]["objective_id"] == "obj-corrosion"
    assert "corrosion current density is reported as 0.4 uA/cm2." in [
        claim["statement"] for claim in understanding["claims"]
    ]
    assert "Heat treatment improves the corrosion response." in [
        claim["statement"] for claim in understanding["claims"]
    ]
    assert understanding["claims"][0]["status"] == "supported"
    assert understanding["claims"][0]["evidence_ref_ids"]
    assert understanding["relations"][0]["relation_type"] == "improves"
    assert understanding["relations"][0]["subject"] == "sample: heat-treated"
    assert understanding["evidence_refs"][0]["fact_ids"] == ["oeu-corrosion"]
    assert understanding["evidence_refs"][0]["label"] == "P001 Table 1"
    assert understanding["contexts"][0]["material_scope"] == ["316L stainless steel"]
    presentation = understanding["presentation"]
    assert presentation["summary"]["title"] == "How does heat treatment affect corrosion resistance?"
    assert presentation["summary"]["material_scope"] == ["316L stainless steel"]
    assert presentation["summary"]["property_scope"] == ["corrosion resistance"]
    assert presentation["summary"]["review_queue_count"] == 0
    assert presentation["effects"][0]["claim_id"] == understanding["claims"][0]["claim_id"]
    assert presentation["effects"][0]["target_property"] == "corrosion resistance"
    assert presentation["effects"][0]["evidence_count"] == 1
    assert presentation["evidence_items"][0]["title"] == "table-1"


def test_material_understanding_projects_findings_measurements_and_relations():
    service = ResearchUnderstandingService()
    evidence_ref = {
        "evidence_ref_id": "E001",
        "source_kind": "table",
        "document_id": "paper-1",
        "locator": "P001 Table 1",
        "fact_ids": ["oeu-density"],
        "anchor_ids": ["anchor-density"],
        "traceability_status": "resolved",
    }
    payload = {
        "collection_id": "col-1",
        "material_id": "mat-316l",
        "canonical_name": "316L stainless steel",
        "overview": {
            "process_families": ["LPBF"],
            "measured_properties": ["relative density"],
        },
        "measured_properties": [
            {
                "property": "relative density",
                "display_range": "98.8-99.6 %",
                "evidence_refs": [evidence_ref],
            }
        ],
        "comparison_groups": [
            {
                "group_id": "group-density",
                "variable_axis": "energy density",
                "comparability_status": "comparable",
                "properties": ["relative density"],
                "evidence_refs": [evidence_ref],
                "matrix": {"matrix_id": "matrix-density"},
                "warnings": [],
            }
        ],
        "evidence_refs": [evidence_ref],
    }

    understanding = service.build_material_understanding(payload)

    ResearchUnderstanding.from_mapping(understanding)
    assert understanding["state"] == "ready"
    assert understanding["scope"]["scope_type"] == "material"
    assert understanding["scope"]["material_id"] == "mat-316l"
    statements = [claim["statement"] for claim in understanding["claims"]]
    assert "relative density is reported as 98.8-99.6 %." in statements
    assert understanding["relations"][0]["subject"] == "energy density"
    assert understanding["relations"][0]["object"] == "relative density"
    assert understanding["evidence_refs"][0]["evidence_ref_id"] == "E001"
    assert understanding["evidence_refs"][0]["label"] == "P001 Table 1"
    assert understanding["evidence_refs"][0]["locator"] == {"source_ref": "P001 Table 1"}
    assert understanding["contexts"][0]["property_scope"] == ["relative density"]
    assert understanding["presentation"]["effects"][0]["title"] == "energy density -> relative density"
    assert understanding["presentation"]["evidence_items"][0]["title"] == "P001 Table 1"


def test_understanding_deduplicates_claims_without_blank_records():
    service = ResearchUnderstandingService()
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-1",
            "question": "Does processing improve strength?",
        },
        "logic_chain": {"summary": "Processing improves strength."},
    }

    understanding = service.build_objective_understanding(payload)

    assert [claim["statement"] for claim in understanding["claims"]] == [
        "Processing improves strength."
    ]


def test_with_presentation_backfills_existing_understanding_without_internal_labels():
    service = ResearchUnderstandingService()
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does LPBF affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_density",
                    "claim_type": "measurement",
                    "statement": "Relative density is reported as 99.1%.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_block"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "relations": [],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_block",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "blk_7483b2607cdb4_7",
                    "locator": {"source_ref": "blk_7483b2607cdb4_7"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "partial",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["laser power"]},
                    "property_scope": ["relative density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    assert understanding["presentation"]["summary"]["title"] == "How does LPBF affect density?"
    assert understanding["presentation"]["effects"][0]["title"] == "laser power -> relative density"
    assert understanding["presentation"]["evidence_items"][0]["title"] == "Text evidence"
