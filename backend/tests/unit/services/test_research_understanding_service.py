from __future__ import annotations

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


class _FakeSemanticRelations:
    def __init__(self, relations: list[dict]) -> None:
        self.relations = [_FakeSemanticRelation(item) for item in relations]


class _FakeSemanticRelation:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def model_dump(self) -> dict:
        return dict(self.payload)


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
    assert extractor.payloads[0]["evidence_units"][1]["sample_context"] == {
        "sample": "heat-treated"
    }
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
