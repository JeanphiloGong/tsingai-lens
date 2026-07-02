from __future__ import annotations

import json

from application.core.research_understanding_service import (
    ResearchUnderstandingService,
)
from domain.core import ResearchUnderstanding
from domain.source import SourceBlock, SourceDocument


class _FakeSourceArtifactRepository:
    def __init__(
        self,
        *,
        blocks: list[SourceBlock] | None = None,
        documents: list[SourceDocument] | None = None,
    ) -> None:
        self.blocks = blocks or []
        self.documents = documents or []

    def list_blocks(self, collection_id: str) -> list[SourceBlock]:
        return self.blocks

    def list_documents(self, collection_id: str) -> list[SourceDocument]:
        return self.documents


class _FakeSemanticExtractor:
    def __init__(self, relations: list[dict] | None = None) -> None:
        self.relations = relations or []
        self.payloads: list[dict] = []

    def extract_research_understanding_relations(self, payload: dict):
        self.payloads.append(payload)
        return _FakeSemanticRelations(self.relations)


class _FailingSemanticExtractor:
    def extract_research_understanding_relations(self, payload: dict):
        raise RuntimeError("relation extractor unavailable")


class _FakeSemanticRelations:
    def __init__(self, relations: list[dict]) -> None:
        self.relations = [_FakeSemanticRelation(item) for item in relations]


class _FakeSemanticRelation:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def model_dump(self) -> dict:
        return dict(self.payload)


def _oversized_relation_payload(unit_count: int = 28) -> dict:
    long_details = " ".join(
        f"metallography preparation route and measurement caveat {index}"
        for index in range(30)
    )
    evidence_units = []
    for index in range(unit_count):
        evidence_units.append(
            {
                "evidence_unit_id": f"oeu-density-{index}",
                "document_id": f"paper-{index % 6}",
                "unit_kind": "measurement" if index % 3 else "comparison",
                "property_normalized": "relative density",
                "material_system": {"alloy": "316L stainless steel"},
                "process_context": {
                    "process": "LPBF",
                    "laser_power": f"{180 + index} W",
                    "scan_speed": f"{700 + index} mm/s",
                },
                "sample_context": {"sample": f"S{index}"},
                "test_condition": {
                    "method": "Archimedes",
                    "details": long_details,
                },
                "value_payload": {
                    "comparison_axis": "laser power",
                    "direction": "increases",
                    "source_value_text": f"{97 + (index % 20) / 10:.1f} %",
                    "summary": "laser power changes relative density",
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": f"table-{index}",
                        "display_label": f"P{index:03d} Table 1",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.85,
            }
        )
    return {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-density",
            "question": "How do LPBF parameters affect relative density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power", "scan speed"],
            "property_axes": ["relative density"],
        },
        "objective_context": {
            "objective_id": "obj-density",
            "question": "How do LPBF parameters affect relative density?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["laser power", "scan speed"],
            "target_property_axes": ["relative density"],
        },
        "evidence_units": evidence_units,
        "logic_chain": {
            "evidence_unit_ids": [
                evidence_units[0]["evidence_unit_id"],
                evidence_units[3]["evidence_unit_id"],
            ],
            "summary": "LPBF process parameters affect relative density.",
        },
    }


def test_objective_understanding_projects_claims_relations_and_evidence_refs():
    extractor = _FakeSemanticExtractor(
        [
            {
                "relation_type": "causal",
                "source_concept": "heat treatment",
                "target_concept": "corrosion resistance",
                "mediator_concepts": [],
                "direction": "improves",
                "statement": "Heat treatment improves corrosion resistance.",
                "conditions": ["316L stainless steel"],
                "evidence_unit_ids": ["oeu-comparison"],
                "confidence": 0.82,
                "warnings": [],
            }
        ]
    )
    service = ResearchUnderstandingService(structured_extractor=extractor)
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
    assert understanding["relations"][0]["subject"] == "heat treatment"
    assert understanding["relations"][0]["object"] == "corrosion resistance"
    assert (
        understanding["relations"][0]["statement"]
        == "Heat treatment improves corrosion resistance."
    )
    assert understanding["relations"][0]["conditions"] == ["316L stainless steel"]
    assert understanding["relations"][0]["source_object_ids"] == ["oeu-comparison"]
    relation_units_by_id = {
        unit["evidence_unit_id"]: unit
        for unit in extractor.payloads[0]["evidence_units"]
    }
    assert relation_units_by_id["oeu-comparison"]["sample_summary"] == "heat-treated"
    assert understanding["evidence_refs"][0]["fact_ids"] == ["oeu-corrosion"]
    assert understanding["evidence_refs"][0]["label"] == "P001 Table 1"
    assert understanding["contexts"][0]["material_scope"] == ["316L stainless steel"]
    presentation = understanding["presentation"]
    assert presentation["summary"]["title"] == "How does heat treatment affect corrosion resistance?"
    assert presentation["summary"]["material_scope"] == ["316L stainless steel"]
    assert presentation["summary"]["property_scope"] == ["corrosion resistance"]
    assert presentation["summary"]["review_queue_count"] == 1
    assert presentation["effects"][0]["claim_id"] == understanding["claims"][0]["claim_id"]
    assert presentation["effects"][0]["target_property"] == "corrosion current density"
    assert presentation["effects"][0]["evidence_count"] == 1
    assert presentation["effects"][0]["needs_review"] is False
    assert presentation["evidence_items"][0]["title"] == "table-1"


def test_objective_relation_payload_excludes_full_audit_context_details():
    extractor = _FakeSemanticExtractor()
    service = ResearchUnderstandingService(structured_extractor=extractor)

    service.build_objective_understanding(_oversized_relation_payload())

    relation_payload = extractor.payloads[0]
    serialized = json.dumps(relation_payload, ensure_ascii=False)
    assert "metallography preparation route and measurement caveat" not in serialized
    assert len(relation_payload["contexts"]) <= 16
    assert len(relation_payload["evidence_units"]) <= 24
    assert relation_payload["evidence_units"][0]["evidence_unit_id"] == "oeu-density-0"
    assert relation_payload["evidence_units"][0]["property_normalized"] == "relative density"
    assert len(serialized) < 30000


def test_objective_relation_payload_prioritizes_relation_worthy_units():
    payload = _oversized_relation_payload(unit_count=30)
    payload["evidence_units"].extend(
        [
            {
                "evidence_unit_id": "oeu-late-comparison",
                "document_id": "paper-9",
                "unit_kind": "comparison",
                "property_normalized": "relative density",
                "value_payload": {
                    "comparison_axis": "scan speed",
                    "direction": "decreases",
                    "source_value_text": "scan speed decreases relative density",
                },
                "resolution_status": "resolved",
                "confidence": 0.87,
            },
            {
                "evidence_unit_id": "oeu-late-interpretation",
                "document_id": "paper-9",
                "unit_kind": "interpretation",
                "property_normalized": "relative density",
                "value_payload": {
                    "summary": "Energy density explains densification changes.",
                },
                "interpretation": "Energy density explains densification changes.",
                "resolution_status": "resolved",
                "confidence": 0.8,
            },
        ]
    )
    payload["logic_chain"]["evidence_unit_ids"] = [
        "oeu-density-0",
        "oeu-late-comparison",
        "oeu-late-interpretation",
    ]
    extractor = _FakeSemanticExtractor()
    service = ResearchUnderstandingService(structured_extractor=extractor)

    service.build_objective_understanding(payload)

    selected_ids = [
        unit["evidence_unit_id"]
        for unit in extractor.payloads[0]["evidence_units"]
    ]
    assert len(selected_ids) == 24
    assert "oeu-density-0" in selected_ids
    assert "oeu-late-comparison" in selected_ids[:8]
    assert "oeu-late-interpretation" in selected_ids[:8]
    assert selected_ids.index("oeu-late-comparison") < selected_ids.index("oeu-density-1")


def test_objective_relation_extraction_failure_is_visible_in_warnings():
    service = ResearchUnderstandingService(
        structured_extractor=_FailingSemanticExtractor(),
    )

    understanding = service.build_objective_understanding(_oversized_relation_payload())

    assert understanding["relations"] == []
    assert "relation_extraction_failed" in understanding["warnings"]
    assert understanding["presentation"]["summary"]["relation_count"] == 0


def test_objective_understanding_filters_weak_claim_fragments():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-density",
            "question": "How do process parameters affect density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power"],
            "property_axes": ["relative density"],
        },
        "objective_context": {
            "objective_id": "obj-density",
            "question": "How do process parameters affect density?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["laser power"],
            "target_property_axes": ["relative density"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-weak-process",
                "document_id": "paper-1",
                "unit_kind": "process_context",
                "value_payload": {
                    "source_value_text": "Achieved through optimized process parameters",
                },
                "resolution_status": "resolved",
                "confidence": 0.88,
            },
            {
                "evidence_unit_id": "oeu-weak-context",
                "document_id": "paper-1",
                "unit_kind": "context",
                "value_payload": {
                    "source_value_text": "density level and ultimate microstructure",
                },
                "resolution_status": "resolved",
                "confidence": 0.84,
            },
            {
                "evidence_unit_id": "oeu-density",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "relative density",
                "value_payload": {"source_value_text": "99.1 %"},
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-density",
                        "display_label": "P001 Table 2",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            },
            {
                "evidence_unit_id": "oeu-comparison",
                "document_id": "paper-1",
                "unit_kind": "comparison",
                "property_normalized": "relative density",
                "value_payload": {
                    "comparison_axis": "laser power",
                    "direction": "increases",
                    "source_value_text": "laser power increases relative density",
                },
                "source_refs": [
                    {
                        "source_kind": "paragraph",
                        "source_ref": "blk-density",
                        "display_label": "P001 Results",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.82,
            },
        ],
        "logic_chain": {
            "evidence_unit_ids": ["oeu-density", "oeu-comparison"],
            "summary": "Optimized laser power improves relative density.",
        },
    }

    understanding = service.build_objective_understanding(payload)

    statements = [claim["statement"] for claim in understanding["claims"]]
    assert "Achieved through optimized process parameters" not in statements
    assert "density level and ultimate microstructure" not in statements
    assert "relative density is reported as 99.1 %." in statements
    assert "laser power increases relative density" in statements
    assert "Optimized laser power improves relative density." in statements
    assert all(claim["claim_type"] != "context" for claim in understanding["claims"])


def test_objective_understanding_binds_claim_specific_context_boundaries():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power"],
            "property_axes": ["relative density"],
        },
        "objective_context": {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["laser power"],
            "target_property_axes": ["relative density"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-density",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "relative density",
                "material_system": {"alloy": "316L stainless steel"},
                "process_context": {"process": "LPBF", "laser_power": "200 W"},
                "sample_context": {"sample": "S2"},
                "test_condition": {"method": "Archimedes"},
                "value_payload": {"source_value_text": "99.1 %"},
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-density",
                        "display_label": "P001 Table 2",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            },
            {
                "evidence_unit_id": "oeu-comparison",
                "document_id": "paper-1",
                "unit_kind": "comparison",
                "property_normalized": "relative density",
                "process_context": {"process": "LPBF", "scan_speed": "800 mm/s"},
                "value_payload": {
                    "comparison_axis": "scan speed",
                    "direction": "decreases",
                    "source_value_text": "scan speed decreases relative density",
                },
                "source_refs": [
                    {
                        "source_kind": "paragraph",
                        "source_ref": "blk-density",
                        "display_label": "P001 Results",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.82,
            },
        ],
        "logic_chain": {
            "evidence_unit_ids": ["oeu-density", "oeu-comparison"],
            "summary": "Laser parameters affect relative density.",
        },
    }

    understanding = service.build_objective_understanding(payload)

    contexts_by_id = {
        context["context_id"]: context for context in understanding["contexts"]
    }
    density_claim = next(
        claim
        for claim in understanding["claims"]
        if claim["statement"] == "relative density is reported as 99.1 %."
    )
    density_context_ids = density_claim["context_ids"]
    assert density_context_ids == ["ctx_oeu-density_boundary"]
    density_context = contexts_by_id[density_context_ids[0]]
    assert density_context["label"] == "Claim applicability"
    assert density_context["material_scope"] == ["316L stainless steel"]
    assert density_context["process_context"] == {
        "process_context": {"process": "LPBF", "laser_power": "200 W"},
        "sample_context": {"sample": "S2"},
    }
    assert density_context["test_condition"] == {"method": "Archimedes"}
    assert density_context["property_scope"] == ["relative density"]

    summary_claim = next(
        claim
        for claim in understanding["claims"]
        if claim["statement"] == "Laser parameters affect relative density."
    )
    assert "ctx_objective_scope" in summary_claim["context_ids"]
    assert "ctx_oeu-density_boundary" in summary_claim["context_ids"]
    assert "ctx_oeu-comparison_boundary" in summary_claim["context_ids"]
    density_effect = next(
        effect
        for effect in understanding["presentation"]["effects"]
        if effect["claim_id"] == density_claim["claim_id"]
    )
    assert (
        density_effect["context_summary"]
        == "316L stainless steel, LPBF, 200 W, S2, Archimedes"
    )


def test_objective_understanding_prioritizes_high_value_evidence_refs():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power"],
            "property_axes": ["relative density"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-density",
                "document_id": "paper-1",
                "unit_kind": "measurement",
                "property_normalized": "relative density",
                "value_payload": {"source_value_text": "99.1 %"},
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "abstract",
                        "display_label": "P001 Abstract",
                        "quote": "The abstract mentions density.",
                    },
                    {
                        "source_kind": "table",
                        "source_ref": "table-results",
                        "display_label": "P001 Table 2 Results",
                        "quote": "Relative density is measured as 99.1 %.",
                    },
                    {
                        "source_kind": "text_window",
                        "source_ref": "results-paragraph",
                        "display_label": "P001 Results paragraph",
                        "quote": "The results section reports relative density.",
                    },
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        ],
    }

    understanding = service.build_objective_understanding(payload)

    claim = understanding["claims"][0]
    evidence_by_id = {
        ref["evidence_ref_id"]: ref for ref in understanding["evidence_refs"]
    }
    claim_labels = [
        evidence_by_id[evidence_ref_id]["label"]
        for evidence_ref_id in claim["evidence_ref_ids"]
    ]
    assert claim_labels == [
        "P001 Table 2 Results",
        "P001 Results paragraph",
        "P001 Abstract",
    ]
    presentation_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    first_item = presentation_by_id[claim["evidence_ref_ids"][0]]
    assert first_item["title"] == "table-results"
    assert first_item["quote"] == "Relative density is measured as 99.1 %."


def test_material_understanding_projects_findings_measurements_and_relations():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
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
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
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


def test_objective_understanding_does_not_project_low_level_comparisons_as_relations():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-density",
            "question": "How does LPBF affect density?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power"],
            "property_axes": ["density"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-row-1",
                "document_id": "paper-1",
                "unit_kind": "comparison",
                "property_normalized": "density",
                "sample_context": {"sample_number": "2"},
                "baseline_context": {"sample_number": "1"},
                "value_payload": {
                    "comparison_axis": "laser power",
                    "direction": "increase",
                    "source_value_text": "sample 2 shows higher density than sample 1",
                },
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        ],
    }

    understanding = service.build_objective_understanding(payload)

    assert understanding["claims"]
    assert understanding["relations"] == []
    assert understanding["presentation"]["summary"]["relation_count"] == 0


def test_with_presentation_backfills_existing_understanding_without_internal_labels():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-1",
                    human_readable_id=1,
                    title="LPBF 316L density study",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk_7483b2607cdb4_7",
                    document_id="paper-1",
                    block_type="paragraph",
                    text="Relative density is reported as 99.1% for the LPBF sample.",
                    block_order=7,
                    page=4,
                    heading_path="Results / Density",
                )
            ],
        ),
    )
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
    assert (
        understanding["presentation"]["effects"][0]["title"]
        == "Relative density is reported as 99.1%."
    )
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert evidence_item["title"] == "LPBF 316L density study / p. 4"
    assert evidence_item["block_type"] == "paragraph"
    assert evidence_item["heading_path"] == "Results / Density"
    assert (
        evidence_item["source_text"]
        == "Relative density is reported as 99.1% for the LPBF sample."
    )


def test_with_presentation_keeps_only_reviewable_direct_relations():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
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
                    "claim_type": "comparison",
                    "statement": "Laser power increases relative density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_laser_density",
                    "relation_type": "increases",
                    "subject": "laser power",
                    "predicate": "increases",
                    "object": "relative density",
                    "statement": None,
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                },
                {
                    "relation_id": "rel_internal_sample",
                    "relation_type": "increases",
                    "subject": "sample_number: 2",
                    "predicate": "increases",
                    "object": "sample_context: {'sample': 2}",
                    "statement": None,
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                },
                {
                    "relation_id": "rel_context_only",
                    "relation_type": "explains",
                    "subject": "build orientation",
                    "predicate": "explains",
                    "object": "texture",
                    "statement": "Build orientation explains texture changes.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_texture"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_texture"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P001 Table 1",
                    "locator": {"source_ref": "table-1"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                },
                {
                    "evidence_ref_id": "evref_texture",
                    "source_kind": "text_window",
                    "document_id": "paper-2",
                    "label": "P002 Results",
                    "locator": {"source_ref": "blk-texture"},
                    "fact_ids": ["unit_texture"],
                    "traceability_status": "resolved",
                },
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
    effect = understanding["presentation"]["effects"][0]
    assert effect["relation_ids"] == ["rel_laser_density"]
    assert effect["effect_direction"] == "increases"


def test_with_presentation_review_queue_uses_effect_level_risks():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
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
                    "claim_id": "claim_measurement",
                    "claim_type": "measurement",
                    "statement": "Relative density is reported as 99.1%.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_density"],
                    "source_object_ids": ["unit_density"],
                },
                {
                    "claim_id": "claim_comparison",
                    "claim_type": "comparison",
                    "statement": "Laser power increases relative density.",
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_comparison"],
                    "context_ids": ["ctx_density"],
                    "source_object_ids": ["unit_comparison"],
                },
            ],
            "relations": [],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P001 Table 1",
                    "locator": {"source_ref": "table-1"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                },
                {
                    "evidence_ref_id": "evref_comparison",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_comparison"],
                    "traceability_status": "resolved",
                    "quote": "Laser power increases relative density.",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_density",
                    "label": "Claim applicability",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "LPBF"},
                    "property_scope": ["relative density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    effects_by_claim_id = {
        effect["claim_id"]: effect
        for effect in understanding["presentation"]["effects"]
    }
    assert effects_by_claim_id["claim_measurement"]["needs_review"] is False
    assert effects_by_claim_id["claim_comparison"]["needs_review"] is True
    assert understanding["presentation"]["summary"]["review_queue_count"] == 1
