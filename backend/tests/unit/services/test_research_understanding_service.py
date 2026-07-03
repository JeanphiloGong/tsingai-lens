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
    assert "corrosion current density is reported as 0.4 uA/cm2." not in [
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
    assert presentation["effects"][0]["target_property"] == "corrosion resistance"
    assert presentation["effects"][0]["evidence_count"] == 1
    assert presentation["effects"][0]["needs_review"] is True
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
    payload = _oversized_relation_payload()
    payload["evidence_units"][0]["value_payload"][
        "summary"
    ] = "Laser power increases relative density."
    service = ResearchUnderstandingService(
        structured_extractor=_FailingSemanticExtractor(),
    )

    understanding = service.build_objective_understanding(payload)

    assert understanding["relations"]
    assert "relation_extraction_failed" in understanding["warnings"]
    assert understanding["presentation"]["summary"]["relation_count"] == len(
        understanding["relations"]
    )
    assert any(
        "deterministic_relation" in relation["warnings"]
        for relation in understanding["relations"]
    )


def test_objective_understanding_projects_deterministic_relations_from_evidence_units():
    payload = _oversized_relation_payload(unit_count=4)
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-comparison",
            "document_id": "paper-1",
            "unit_kind": "comparison",
            "property_normalized": "relative density",
            "value_payload": {
                "comparison_axis": "scan speed",
                "direction": "decreases",
                "source_value_text": "scan speed decreases relative density",
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "blk-results",
                    "display_label": "P001 Results",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.87,
        },
        {
            "evidence_unit_id": "oeu-plain-measurement",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "relative density",
            "value_payload": {"source_value_text": "99.1 %"},
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    ]
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())

    understanding = service.build_objective_understanding(payload)

    relation = understanding["relations"][0]
    assert relation["subject"] == "scan speed"
    assert relation["predicate"] == "decreases"
    assert relation["object"] == "relative density"
    assert relation["source_object_ids"] == ["oeu-comparison"]
    assert relation["evidence_ref_ids"]
    assert "deterministic_relation" in relation["warnings"]
    assert all(
        "oeu-plain-measurement" not in relation["source_object_ids"]
        for relation in understanding["relations"]
    )


def test_objective_understanding_projects_density_effect_relation_from_statement():
    payload = _oversized_relation_payload(unit_count=4)
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-density-effect",
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "density",
            "sample_context": {
                "test_method": "heat treatment",
                "test_type": "hot isostatic pressing",
            },
            "process_context": {"process": "selective laser melting"},
            "baseline_context": {"test_method": "as-SLM"},
            "value_payload": {"source_value_text": "97.83%", "value": 97.83},
            "interpretation": "The heat treatment process reduces density compared to the as-SLM condition.",
            "source_refs": [
                {
                    "source_kind": "paragraph",
                    "source_ref": "blk-density-effect",
                    "display_label": "P001 Results",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.83,
        },
        {
            "evidence_unit_id": "oeu-sample-rank",
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "relative density",
            "value_payload": {
                "summary": "Sample 24 has the highest table-derived relative density at 98.75%.",
            },
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-density",
                    "display_label": "P001 Table 2",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.85,
        },
    ]
    payload["logic_chain"]["summary"] = ""
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())

    understanding = service.build_objective_understanding(payload)

    assert [claim["statement"] for claim in understanding["claims"]] == [
        "The heat treatment process reduces density compared to the as-SLM condition."
    ]
    assert len(understanding["relations"]) == 1
    relation = understanding["relations"][0]
    assert relation["subject"] == "heat treatment"
    assert relation["predicate"] == "reduces"
    assert relation["object"] == "density"
    assert relation["source_object_ids"] == ["oeu-density-effect"]
    effect = understanding["presentation"]["effects"][0]
    assert effect["relation_ids"] == [relation["relation_id"]]


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
    assert "relative density is reported as 99.1 %." not in statements
    assert "laser power increases relative density" in statements
    assert "Optimized laser power improves relative density." in statements
    assert all(claim["claim_type"] != "context" for claim in understanding["claims"])


def test_objective_understanding_prioritizes_relation_claims_over_measurements():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = _oversized_relation_payload(unit_count=14)
    payload["evidence_units"].extend(
        [
            {
                "evidence_unit_id": "oeu-laser-density",
                "document_id": "paper-1",
                "unit_kind": "comparison",
                "property_normalized": "relative density",
                "process_context": {"process": "LPBF", "laser_power": "220 W"},
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
                "confidence": 0.86,
            },
            {
                "evidence_unit_id": "oeu-heat-microstructure",
                "document_id": "paper-2",
                "unit_kind": "interpretation",
                "property_normalized": "microstructure",
                "process_context": {"heat_treatment": "solution annealing"},
                "value_payload": {
                    "summary": "heat treatment reduces carbide and ferrite features",
                },
                "interpretation": "heat treatment reduces carbide and ferrite features",
                "source_refs": [
                    {
                        "source_kind": "paragraph",
                        "source_ref": "blk-microstructure",
                        "display_label": "P002 Discussion",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.81,
            },
        ]
    )
    payload["logic_chain"]["evidence_unit_ids"] = [
        "oeu-laser-density",
        "oeu-heat-microstructure",
    ]
    payload["logic_chain"][
        "summary"
    ] = "Laser power and heat treatment affect density and microstructure."

    understanding = service.build_objective_understanding(payload)

    statements = [claim["statement"] for claim in understanding["claims"]]
    claim_types = [claim["claim_type"] for claim in understanding["claims"]]
    assert statements[:2] == [
        "laser power increases relative density",
        "Laser power and heat treatment affect density and microstructure.",
    ]
    assert "heat treatment reduces carbide and ferrite features" not in statements
    assert claim_types[:2] == ["comparison", "finding"]
    measurement_claims = [
        claim for claim in understanding["claims"] if claim["claim_type"] == "measurement"
    ]
    assert measurement_claims == []
    assert all(claim["evidence_ref_ids"] for claim in understanding["claims"])
    assert understanding["relations"]
    assert understanding["presentation"]["summary"]["relation_count"] == len(
        understanding["relations"]
    )


def test_objective_understanding_keeps_mediator_observations_out_of_claims():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-corrosion",
            "question": "How does LPBF affect pitting potential?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power"],
            "property_axes": ["pitting potential"],
        },
        "objective_context": {
            "objective_id": "obj-corrosion",
            "question": "How does LPBF affect pitting potential?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["laser power"],
            "target_property_axes": ["pitting potential"],
            "objective_evidence_lens": {
                "target_outcome_axes": ["pitting potential"],
                "mediator_axes": ["lack of fusion", "porosity", "fatigue cracks"],
            },
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-defects",
                "document_id": "paper-1",
                "unit_kind": "characterization",
                "property_normalized": "lack of fusion defects",
                "value_payload": {
                    "summary": (
                        "Lack of fusion defects and fatigue cracks were observed "
                        "near melt pool boundaries."
                    ),
                },
                "source_refs": [
                    {
                        "source_kind": "paragraph",
                        "source_ref": "blk-defects",
                        "display_label": "P001 Results",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.83,
            },
            {
                "evidence_unit_id": "oeu-pitting",
                "document_id": "paper-1",
                "unit_kind": "comparison",
                "property_normalized": "pitting potential",
                "value_payload": {
                    "comparison_axis": "laser power",
                    "direction": "increases",
                    "source_value_text": "laser power increases pitting potential",
                },
                "source_refs": [
                    {
                        "source_kind": "paragraph",
                        "source_ref": "blk-pitting",
                        "display_label": "P001 Corrosion",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.87,
            },
        ],
        "logic_chain": {
            "evidence_unit_ids": ["oeu-defects", "oeu-pitting"],
            "summary": "Laser power improves pitting potential.",
        },
    }

    understanding = service.build_objective_understanding(payload)

    statements = [claim["statement"] for claim in understanding["claims"]]
    assert (
        "Lack of fusion defects and fatigue cracks were observed near melt pool boundaries."
        not in statements
    )
    assert "laser power increases pitting potential" in statements
    assert "Laser power improves pitting potential." in statements


def test_objective_understanding_blocks_real_corrosion_mediators_and_propagates_evidence_role():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            blocks=[
                SourceBlock(
                    block_id="blk-lof-defects",
                    document_id="paper-3",
                    block_type="paragraph",
                    text=(
                        "LoF defects located at melt pool boundaries and pore size "
                        "changes were observed in the SLM samples."
                    ),
                    block_order=18,
                    page=6,
                    heading_path="Results / Defects",
                ),
                SourceBlock(
                    block_id="blk-corrosion",
                    document_id="paper-5",
                    block_type="paragraph",
                    text=(
                        "Pitting corrosion resistance improved after the passive "
                        "film became more stable."
                    ),
                    block_order=24,
                    page=9,
                    heading_path="Results / Corrosion",
                ),
            ]
        ),
    )
    payload = {
        "collection_id": "col-real",
        "objective": {
            "objective_id": "obj-pitting",
            "question": "What affects pitting corrosion behavior?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["SLM"],
            "property_axes": ["pitting corrosion behavior"],
        },
        "objective_context": {
            "objective_id": "obj-pitting",
            "target_property_axes": ["pitting corrosion behavior"],
            "objective_evidence_lens": {
                "target_outcome_axes": ["pitting corrosion behavior"],
                "mediator_axes": ["lack of fusion", "pore size", "porosity"],
            },
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-lof",
                "document_id": "paper-3",
                "unit_kind": "characterization",
                "property_normalized": "lack of fusion defects",
                "value_payload": {
                    "summary": (
                        "LoF defects located at melt pool boundaries and pore size "
                        "changes were observed in the SLM samples."
                    ),
                },
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "blk-lof-defects",
                        "role": "characterization",
                        "evidence_role": "mediator_context",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.84,
            },
            {
                "evidence_unit_id": "oeu-corrosion",
                "document_id": "paper-5",
                "unit_kind": "interpretation",
                "property_normalized": "pitting corrosion behavior",
                "value_payload": {
                    "summary": (
                        "Pitting corrosion resistance improved after the passive "
                        "film became more stable."
                    ),
                },
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "blk-corrosion",
                        "role": "current_experimental_evidence",
                        "evidence_role": "direct_support",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.88,
            },
        ],
        "logic_chain": {
            "evidence_unit_ids": ["oeu-lof", "oeu-corrosion"],
            "summary": "Stable passive film improves pitting corrosion behavior.",
        },
    }

    understanding = service.build_objective_understanding(payload)

    statements = [claim["statement"] for claim in understanding["claims"]]
    assert all("LoF defects" not in statement for statement in statements)
    assert all("pore size" not in statement for statement in statements)
    assert (
        "Pitting corrosion resistance improved after the passive film became more stable."
        in statements
    )
    assert "Stable passive film improves pitting corrosion behavior." in statements
    evidence_by_ref = {
        ref["locator"]["source_ref"]: ref for ref in understanding["evidence_refs"]
    }
    assert (
        evidence_by_ref["blk-corrosion"]["quote"]
        == "Pitting corrosion resistance improved after the passive film became more stable."
    )
    assert evidence_by_ref["blk-corrosion"]["locator"]["page"] == 9
    assert evidence_by_ref["blk-corrosion"]["document_id"] == "paper-5"
    assert evidence_by_ref["blk-corrosion"]["evidence_role"] == "direct_support"
    assert evidence_by_ref["blk-lof-defects"]["evidence_role"] == "mediator_context"
    presentation_by_ref = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    corrosion_ref_id = evidence_by_ref["blk-corrosion"]["evidence_ref_id"]
    defects_ref_id = evidence_by_ref["blk-lof-defects"]["evidence_ref_id"]
    assert presentation_by_ref[corrosion_ref_id]["evidence_role"] == "direct_support"
    assert presentation_by_ref[defects_ref_id]["evidence_role"] == "mediator_context"


def test_objective_understanding_blocks_real_density_background_from_claims():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = _oversized_relation_payload(unit_count=4)
    payload["objective"]["question"] = "How do LPBF parameters affect density and microstructure?"
    payload["objective"]["property_axes"] = ["relative density", "microstructure"]
    payload["objective_context"]["question"] = (
        "How do LPBF parameters affect density and microstructure?"
    )
    payload["objective_context"]["target_property_axes"] = [
        "relative density",
        "microstructure",
    ]
    payload["objective_context"]["objective_evidence_lens"] = {
        "target_outcome_axes": ["relative density", "microstructure"],
        "mediator_axes": ["porosity defects", "pore size"],
        "context_axes": ["LPBF process window"],
    }
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-porosity",
            "document_id": "paper-4",
            "unit_kind": "characterization",
            "property_normalized": "porosity defects",
            "value_payload": {
                "summary": (
                    "Porosity defects observed in the low-energy-density samples "
                    "were mostly lack-of-fusion pores."
                ),
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "blk-porosity",
                    "role": "characterization",
                    "evidence_role": "mediator_context",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.82,
        },
        {
            "evidence_unit_id": "oeu-density",
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
                    "source_kind": "text_window",
                    "source_ref": "blk-density",
                    "role": "current_experimental_evidence",
                    "evidence_role": "direct_support",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.87,
        },
    ]
    payload["logic_chain"]["summary"] = (
        "Laser power affects relative density in the reviewed LPBF samples."
    )
    payload["logic_chain"]["evidence_unit_ids"] = ["oeu-porosity", "oeu-density"]

    understanding = service.build_objective_understanding(payload)

    statements = [claim["statement"] for claim in understanding["claims"]]
    assert all("Porosity defects observed" not in statement for statement in statements)
    assert "laser power increases relative density" in statements
    assert (
        "Laser power affects relative density in the reviewed LPBF samples."
        in statements
    )


def test_objective_understanding_blocks_real_fatigue_future_work_from_claims():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = _oversized_relation_payload(unit_count=4)
    payload["objective"]["question"] = "How do LPBF parameters affect fatigue performance?"
    payload["objective"]["property_axes"] = ["fatigue performance"]
    payload["objective_context"]["question"] = (
        "How do LPBF parameters affect fatigue performance?"
    )
    payload["objective_context"]["target_property_axes"] = ["fatigue performance"]
    payload["objective_context"]["objective_evidence_lens"] = {
        "target_outcome_axes": ["fatigue performance"],
        "mediator_axes": ["porosity", "surface roughness"],
    }
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-fatigue-assumption",
            "document_id": "paper-2",
            "unit_kind": "interpretation",
            "property_normalized": "fatigue performance",
            "value_payload": {
                "summary": (
                    "fatigue performance is assumed to improve after porosity "
                    "reduction but remains to be studied."
                ),
            },
            "interpretation": (
                "fatigue performance is assumed to improve after porosity "
                "reduction but remains to be studied."
            ),
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "blk-fatigue-future",
                    "role": "current_experimental_evidence",
                    "evidence_role": "direct_support",
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.74,
        }
    ]
    payload["logic_chain"]["summary"] = (
        "Future work should verify whether porosity reduction improves fatigue performance."
    )
    payload["logic_chain"]["evidence_unit_ids"] = ["oeu-fatigue-assumption"]

    understanding = service.build_objective_understanding(payload)

    assert understanding["claims"] == []


def test_objective_understanding_blocks_observed_defect_characterization_claims():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = _oversized_relation_payload(unit_count=4)
    payload["objective"]["question"] = "How do defects affect pitting corrosion behavior?"
    payload["objective"]["property_axes"] = ["pitting corrosion behavior"]
    payload["objective_context"]["question"] = (
        "How do defects affect pitting corrosion behavior?"
    )
    payload["objective_context"]["target_property_axes"] = [
        "pitting corrosion behavior"
    ]
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-lof-observed",
            "document_id": "paper-1",
            "unit_kind": "characterization",
            "property_normalized": "pitting corrosion behavior",
            "value_payload": {
                "summary": (
                    "LoF defects located at melt pool boundaries with elongated "
                    "truncated shape are observed."
                ),
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "blk-lof",
                    "role": "characterization",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.85,
        }
    ]
    payload["logic_chain"]["summary"] = ""
    payload["logic_chain"]["evidence_unit_ids"] = ["oeu-lof-observed"]

    understanding = service.build_objective_understanding(payload)

    assert understanding["claims"] == []


def test_objective_understanding_does_not_match_dislocation_density_as_density_claim():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = _oversized_relation_payload(unit_count=4)
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-dislocation-density",
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "dislocation density",
            "value_payload": {
                "summary": "heat treatment reduces dislocation density after deformation",
            },
            "interpretation": "heat treatment reduces dislocation density after deformation",
            "source_refs": [
                {
                    "source_kind": "paragraph",
                    "source_ref": "blk-dislocation-density",
                    "display_label": "P001 Discussion",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.82,
        }
    ]
    payload["objective"]["property_axes"] = ["density"]
    payload["objective_context"]["target_property_axes"] = ["density"]
    payload["logic_chain"]["summary"] = "Heat treatment reduces dislocation density."
    payload["logic_chain"]["evidence_unit_ids"] = ["oeu-dislocation-density"]

    understanding = service.build_objective_understanding(payload)

    assert understanding["claims"] == []


def test_objective_understanding_filters_future_work_claims():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = _oversized_relation_payload(unit_count=4)
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-future",
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "relative density",
            "value_payload": {
                "summary": (
                    "Future work should investigate whether scan speed improves "
                    "relative density."
                ),
            },
            "interpretation": (
                "Future work should investigate whether scan speed improves "
                "relative density."
            ),
            "source_refs": [
                {
                    "source_kind": "paragraph",
                    "source_ref": "blk-future-work",
                    "display_label": "P001 Conclusion",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.78,
        }
    ]
    payload["logic_chain"]["summary"] = (
        "Future work should investigate whether scan speed improves relative density."
    )
    payload["logic_chain"]["evidence_unit_ids"] = ["oeu-future"]

    understanding = service.build_objective_understanding(payload)

    assert understanding["claims"] == []


def test_objective_understanding_filters_noisy_claim_entry_fragments():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = _oversized_relation_payload(unit_count=4)
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-sample-rank",
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "relative density",
            "value_payload": {
                "summary": "Sample 24 has the highest table-derived relative density at 98.75%.",
            },
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-density",
                    "display_label": "P001 Table 2",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.85,
        },
        {
            "evidence_unit_id": "oeu-measurement-reference",
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "density",
            "value_payload": {
                "summary": "The density measurement is relative to the conventional 316L stainless steel reference value.",
            },
            "source_refs": [
                {
                    "source_kind": "paragraph",
                    "source_ref": "blk-density-reference",
                    "display_label": "P001 Methods",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.84,
        },
        {
            "evidence_unit_id": "oeu-report-fragment",
            "document_id": "paper-2",
            "unit_kind": "characterization",
            "property_normalized": "microstructure",
            "value_payload": {
                "summary": "microstructure is reported as melt pool analysis.",
            },
            "source_refs": [
                {
                    "source_kind": "paragraph",
                    "source_ref": "blk-microstructure",
                    "display_label": "P002 Results",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.82,
        },
        {
            "evidence_unit_id": "oeu-valid-mechanism",
            "document_id": "paper-2",
            "unit_kind": "interpretation",
            "property_normalized": "microstructure",
            "process_context": {"process": "selective laser melting"},
            "value_payload": {
                "summary": "increase in applied energy density results in coarser grains",
            },
            "source_refs": [
                {
                    "source_kind": "paragraph",
                    "source_ref": "blk-grains",
                    "display_label": "P002 Discussion",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.88,
        },
    ]
    payload["logic_chain"]["summary"] = ""

    understanding = service.build_objective_understanding(payload)

    statements = [claim["statement"] for claim in understanding["claims"]]
    assert statements == [
        "increase in applied energy density results in coarser grains"
    ]
    assert understanding["presentation"]["summary"]["evidence_count"] == 4


def test_objective_understanding_filters_aggregate_logic_summary_claims():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = _oversized_relation_payload(unit_count=4)
    payload["evidence_units"].append(
        {
            "evidence_unit_id": "oeu-valid-mechanism",
            "document_id": "paper-2",
            "unit_kind": "interpretation",
            "property_normalized": "microstructure",
            "process_context": {"process": "selective laser melting"},
            "value_payload": {
                "summary": "increase in applied energy density results in coarser grains",
            },
            "source_refs": [
                {
                    "source_kind": "paragraph",
                    "source_ref": "blk-grains",
                    "display_label": "P002 Discussion",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.88,
        }
    )
    payload["logic_chain"]["evidence_unit_ids"] = [
        unit["evidence_unit_id"] for unit in payload["evidence_units"]
    ]
    payload["logic_chain"][
        "summary"
    ] = "How does processing affect 316L?: 43 measurement unit(s) across 6 document(s); density range 90.04-99.45 %; table 2 > laser energy density range 3.0-3.0 J/mm3."

    understanding = service.build_objective_understanding(payload)

    statements = [claim["statement"] for claim in understanding["claims"]]
    assert "increase in applied energy density results in coarser grains" in statements
    assert all("measurement unit(s)" not in statement for statement in statements)
    assert all("density range" not in statement for statement in statements)


def test_objective_understanding_filters_real_assembled_logic_summary_claims():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = _oversized_relation_payload(unit_count=4)
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-density",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "density",
            "value_payload": {"source_value_text": "98.33 %"},
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "tbl-density",
                    "evidence_role": "direct_support",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    ]
    payload["logic_chain"]["evidence_unit_ids"] = ["oeu-density"]
    payload["logic_chain"]["summary"] = (
        "How do laser power and scan speed affect density?: assembled 43 "
        "measurement unit(s) across 6 document(s); density range 90.04-99.45 %."
    )

    understanding = service.build_objective_understanding(payload)

    statements = [claim["statement"] for claim in understanding["claims"]]
    assert all("assembled 43 measurement unit(s)" not in item for item in statements)
    assert all("density range" not in item for item in statements)


def test_objective_understanding_keeps_measurement_only_claims():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = _oversized_relation_payload(unit_count=14)
    for index, unit in enumerate(payload["evidence_units"]):
        unit["unit_kind"] = "measurement"
        unit["value_payload"] = {"source_value_text": f"99.{index} %"}
    payload["logic_chain"]["summary"] = ""

    understanding = service.build_objective_understanding(payload)

    assert len(understanding["claims"]) == 12
    assert {claim["claim_type"] for claim in understanding["claims"]} == {
        "measurement"
    }


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
    density_context = contexts_by_id["ctx_oeu-density_boundary"]
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
        if effect["statement"] == "scan speed decreases relative density"
    )
    assert (
        density_effect["context_summary"]
        == "316L stainless steel, LPBF, 800 mm/s"
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


def test_objective_understanding_enriches_evidence_refs_with_source_block_quote():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            blocks=[
                SourceBlock(
                    block_id="blk-density-results",
                    document_id="paper-1",
                    block_type="paragraph",
                    text="Relative density reached 99.1% after laser power optimization.",
                    block_order=12,
                    page=5,
                    heading_path="Results / Density",
                )
            ]
        ),
    )
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "property_axes": ["relative density"],
        },
        "objective_context": {
            "objective_id": "obj-density",
            "target_property_axes": ["relative density"],
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
                        "source_ref": "blk-density-results",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        ],
    }

    understanding = service.build_objective_understanding(payload)

    evidence_ref = understanding["evidence_refs"][0]
    assert (
        evidence_ref["quote"]
        == "Relative density reached 99.1% after laser power optimization."
    )
    assert evidence_ref["locator"]["source_ref"] == "blk-density-results"
    assert evidence_ref["locator"]["page"] == 5
    assert evidence_ref["document_id"] == "paper-1"


def test_objective_understanding_preserves_existing_evidence_ref_quote():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            blocks=[
                SourceBlock(
                    block_id="blk-density-results",
                    document_id="paper-1",
                    block_type="paragraph",
                    text="Block text should not replace an explicit source quote.",
                    block_order=12,
                    page=5,
                    heading_path="Results / Density",
                )
            ]
        ),
    )
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-density",
            "question": "How does laser power affect relative density?",
            "property_axes": ["relative density"],
        },
        "objective_context": {
            "objective_id": "obj-density",
            "target_property_axes": ["relative density"],
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
                        "source_ref": "blk-density-results",
                        "quote": "Explicit quote from extraction.",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        ],
    }

    understanding = service.build_objective_understanding(payload)

    evidence_ref = understanding["evidence_refs"][0]
    assert evidence_ref["quote"] == "Explicit quote from extraction."
    assert evidence_ref["locator"]["page"] == 5


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

    assert understanding["claims"] == []
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


def test_with_presentation_uses_result_specific_direct_evidence_quote():
    long_block_text = (
        "This study evaluates LPBF 316L samples with and without build "
        "platform preheating to understand broad processing responses. "
        "The introduction summarizes prior work on additive manufacturing "
        "microstructure and mechanical properties. "
        "Results show that build platform preheating reduced thermal "
        "gradients, refined the microstructure, and improved tensile "
        "strength."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-2",
                    human_readable_id=2,
                    title="Preheating effects in LPBF 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-preheat",
                    document_id="paper-2",
                    block_type="paragraph",
                    text=long_block_text,
                    block_order=12,
                    page=8,
                    heading_path="Results / Microstructure",
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
                "title": (
                    "How does build platform preheating affect "
                    "microstructure?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_microstructure",
                    "claim_type": "finding",
                    "statement": (
                        "Build platform preheating improves microstructure "
                        "and mechanical properties."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_microstructure",
                    "relation_type": "improves",
                    "subject": "build platform preheating",
                    "predicate": "improves",
                    "object": "thermal gradients -> microstructure",
                    "statement": (
                        "Build platform preheating improves microstructure by "
                        "reducing thermal gradients."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_preheat",
                    "source_kind": "text_window",
                    "document_id": "paper-2",
                    "label": "P002 Results",
                    "locator": {"source_ref": "blk-preheat"},
                    "fact_ids": ["unit_preheat"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process": "LPBF",
                        "variable_process_axes": ["build platform preheating"],
                    },
                    "property_scope": ["microstructure"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_preheat"]
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert evidence_item["source_text"] == long_block_text
    assert evidence_item["quote"] == (
        "Results show that build platform preheating reduced thermal gradients, "
        "refined the microstructure, and improved tensile strength."
    )


def test_with_presentation_quote_can_use_adjacent_sentences_for_direct_evidence():
    long_block_text = (
        "This study aims to understand the effect of build platform preheating "
        "on microstructural features and mechanical properties. "
        "Two sets of specimens were fabricated on a non-preheated build "
        "platform and the build platform preheated to 150 C. "
        "Microstructural features are analyzed via simulation, and the results "
        "are validated experimentally."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-2",
                    human_readable_id=2,
                    title="Preheating effects in LPBF 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-preheat",
                    document_id="paper-2",
                    block_type="paragraph",
                    text=long_block_text,
                    block_order=12,
                    page=8,
                    heading_path="Abstract",
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
                "title": (
                    "How does build platform preheating affect "
                    "microstructure?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_microstructure",
                    "claim_type": "finding",
                    "statement": (
                        "Build platform preheating changes microstructural "
                        "features."
                    ),
                    "status": "supported",
                    "confidence": 0.8,
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_microstructure",
                    "relation_type": "changes",
                    "subject": "build platform preheating",
                    "predicate": "changes",
                    "object": "microstructure",
                    "statement": (
                        "Build platform preheating changes microstructural "
                        "features."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_preheat",
                    "source_kind": "text_window",
                    "document_id": "paper-2",
                    "label": "P002 Abstract",
                    "locator": {"source_ref": "blk-preheat"},
                    "fact_ids": ["unit_preheat"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process": "LPBF",
                        "variable_process_axes": ["build platform preheating"],
                    },
                    "property_scope": ["microstructure"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert evidence_item["quote"] == (
        "Two sets of specimens were fabricated on a non-preheated build "
        "platform and the build platform preheated to 150 C. Microstructural "
        "features are analyzed via simulation, and the results are validated "
        "experimentally."
    )


def test_with_presentation_prefers_specific_single_sentence_quote():
    long_block_text = (
        "In the current experimental results, the strength does not seem to "
        "noticeable change with the decrease in porosity level and pores size, "
        "but it significantly influences ductility. "
        "Besides, the pores of SLM 316L SS samples have higher sensitivity to "
        "pitting behavior. "
        "Under higher porosity level conditions, the as-fabricated sample was "
        "more prone to pitting, formed unstable passive film, and easy to be "
        "broken down."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-5",
                    human_readable_id=5,
                    title="Porosity and corrosion in SLM 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-corrosion",
                    document_id="paper-5",
                    block_type="paragraph",
                    text=long_block_text,
                    block_order=7,
                    page=1,
                    heading_path="Abstract",
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
                "title": "How does porosity affect pitting corrosion?",
            },
            "claims": [
                {
                    "claim_id": "claim_corrosion",
                    "claim_type": "finding",
                    "statement": (
                        "Higher porosity level increases pitting corrosion "
                        "susceptibility."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_corrosion"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_corrosion"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_porosity_corrosion",
                    "relation_type": "increases",
                    "subject": "porosity level",
                    "predicate": "increases",
                    "object": "pitting corrosion behavior",
                    "statement": (
                        "Higher porosity level increases pitting corrosion "
                        "susceptibility."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_corrosion"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_corrosion"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_corrosion",
                    "source_kind": "text_window",
                    "document_id": "paper-5",
                    "label": "P005 Abstract",
                    "locator": {"source_ref": "blk-corrosion"},
                    "fact_ids": ["unit_corrosion"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "SLM"},
                    "property_scope": ["pitting corrosion behavior"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert evidence_item["quote"] == (
        "Under higher porosity level conditions, the as-fabricated sample was "
        "more prone to pitting, formed unstable passive film, and easy to be "
        "broken down."
    )


def test_with_presentation_prefers_result_bearing_direct_evidence_source():
    abstract_text = (
        "This study aims to understand the effect of build platform "
        "preheating temperature on microstructural features and mechanical "
        "properties in laser beam powder bed fusion."
    )
    conclusion_text = (
        "Conclusions show that preheating to 150 C increased ductility by "
        "14% and this improvement was attributed to homogenized cellular "
        "microstructure after laser beam powder bed fusion. "
        "The size and distribution of porosity also decreased with "
        "preheating."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-2",
                    human_readable_id=2,
                    title="Preheating effects in LPBF 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-abstract",
                    document_id="paper-2",
                    block_type="paragraph",
                    text=abstract_text,
                    block_order=9,
                    page=1,
                    heading_path="Abstract",
                ),
                SourceBlock(
                    block_id="blk-conclusion",
                    document_id="paper-2",
                    block_type="paragraph",
                    text=conclusion_text,
                    block_order=240,
                    page=13,
                    heading_path="Conclusions",
                ),
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
                "title": (
                    "How do build platform preheating temperature and build "
                    "platform preheating affect microstructure?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_microstructure",
                    "claim_type": "finding",
                    "statement": (
                        "Build platform preheating improves microstructure "
                        "and mechanical properties."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_abstract"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_abstract"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_microstructure",
                    "relation_type": "improves",
                    "subject": "build platform preheating",
                    "predicate": "improves",
                    "object": "microstructure",
                    "statement": (
                        "Build platform preheating improves microstructure "
                        "and mechanical properties."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_abstract"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_abstract"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_abstract",
                    "source_kind": "text_window",
                    "document_id": "paper-2",
                    "label": "P002 Abstract",
                    "locator": {"source_ref": "blk-abstract"},
                    "fact_ids": ["unit_abstract"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
                {
                    "evidence_ref_id": "evref_conclusion",
                    "source_kind": "text_window",
                    "document_id": "paper-2",
                    "label": "P002 Conclusions",
                    "locator": {"source_ref": "blk-conclusion"},
                    "fact_ids": ["unit_conclusion"],
                    "traceability_status": "resolved",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process": "laser beam powder bed fusion",
                        "variable_process_axes": ["build platform preheating"],
                    },
                    "property_scope": ["microstructure", "mechanical properties"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_conclusion"]
    assert finding["evidence_bundle"]["uncategorized"] == ["evref_abstract"]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    assert evidence_by_id["evref_conclusion"]["source_text"] == conclusion_text
    assert evidence_by_id["evref_conclusion"]["quote"] == (
        "Conclusions show that preheating to 150 C increased ductility by "
        "14% and this improvement was attributed to homogenized cellular "
        "microstructure after laser beam powder bed fusion."
    )


def test_with_presentation_prefers_concrete_result_sentence_over_lead_in_quote():
    conclusion_text = (
        "The effect of preheating the build platform on the microstructure "
        "and mechanical properties of LBPBF 316L SS was investigated. "
        "The following conclusions can be drawn based on the results: "
        "Preheating the build platform to 150 C increased the ductility of "
        "material by 14%. "
        "This is attributed to the more homogenized microstructure as well "
        "as cellular structure with geometrically necessary dislocations."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-2",
                    human_readable_id=2,
                    title="Preheating effects in LPBF 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-conclusion",
                    document_id="paper-2",
                    block_type="paragraph",
                    text=conclusion_text,
                    block_order=238,
                    page=9,
                    heading_path="Conclusions and future study",
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
                "title": (
                    "How does build platform preheating affect mechanical "
                    "properties?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_mechanical",
                    "claim_type": "finding",
                    "statement": (
                        "Build platform preheating improves mechanical "
                        "properties through microstructure evolution."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_conclusion"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_conclusion"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_mechanical",
                    "relation_type": "improves",
                    "subject": "build platform preheating",
                    "predicate": "improves",
                    "object": "microstructure -> mechanical properties",
                    "statement": (
                        "Build platform preheating improves mechanical "
                        "properties through microstructure evolution."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_conclusion"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_conclusion"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_conclusion",
                    "source_kind": "text_window",
                    "document_id": "paper-2",
                    "label": "P002 Conclusions",
                    "locator": {"source_ref": "blk-conclusion"},
                    "fact_ids": ["unit_conclusion"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process": "laser beam powder bed fusion",
                        "variable_process_axes": ["build platform preheating"],
                    },
                    "property_scope": ["mechanical properties"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert evidence_item["quote"] == (
        "Preheating the build platform to 150 C increased the ductility of "
        "material by 14%. This is attributed to the more homogenized "
        "microstructure as well as cellular structure with geometrically "
        "necessary dislocations."
    )


def test_with_presentation_uses_adjacent_result_block_for_lead_in_quote():
    lead_in_text = (
        "The effect of preheating the build platform on the microstructure "
        "and mechanical properties of LBPBF 316L SS was investigated. "
        "The following conclusions can be drawn based on the results:"
    )
    result_text = (
        "Preheating the build platform to 150 C increased the ductility of "
        "material by 14%. This is attributed to the more homogenized "
        "microstructure as well as cellular structure with geometrically "
        "necessary dislocations."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-2",
                    human_readable_id=2,
                    title="Preheating effects in LPBF 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-conclusion-lead-in",
                    document_id="paper-2",
                    block_type="paragraph",
                    text=lead_in_text,
                    block_order=238,
                    page=9,
                    heading_path="Conclusions and future study",
                ),
                SourceBlock(
                    block_id="blk-conclusion-result",
                    document_id="paper-2",
                    block_type="paragraph",
                    text=result_text,
                    block_order=240,
                    page=9,
                    heading_path="Conclusions and future study",
                ),
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
                "title": (
                    "How does build platform preheating affect mechanical "
                    "properties?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_mechanical",
                    "claim_type": "finding",
                    "statement": (
                        "Build platform preheating improves mechanical "
                        "properties through microstructure evolution."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_conclusion"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_conclusion"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_mechanical",
                    "relation_type": "improves",
                    "subject": "build platform preheating",
                    "predicate": "improves",
                    "object": "microstructure -> mechanical properties",
                    "statement": (
                        "Build platform preheating improves mechanical "
                        "properties through microstructure evolution."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_conclusion"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_conclusion"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_conclusion",
                    "source_kind": "text_window",
                    "document_id": "paper-2",
                    "label": "P002 Conclusions",
                    "locator": {"source_ref": "blk-conclusion-lead-in"},
                    "fact_ids": ["unit_conclusion"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process": "laser beam powder bed fusion",
                        "variable_process_axes": ["build platform preheating"],
                    },
                    "property_scope": ["mechanical properties"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert evidence_item["source_ref"] == "blk-conclusion-lead-in"
    assert evidence_item["source_text"] == result_text
    assert evidence_item["quote"] == result_text


def test_with_presentation_keeps_results_direct_evidence_over_introduction_review():
    results_text = (
        "The achieved density measured using the Archimedes method was 91.9, "
        "98.9 and 99.6 % for L-VED, M-VED and H-VED, respectively."
    )
    intro_text = (
        "Several previous studies reported that laser power can manipulate "
        "density in an optimal VED range, but these reports are reviewed as "
        "background for the present work."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-1",
                    human_readable_id=1,
                    title="VED effects in PBF-LB 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-results",
                    document_id="paper-1",
                    block_type="paragraph",
                    text=results_text,
                    block_order=65,
                    page=3,
                    heading_path="3.1. As-built microstructures",
                ),
                SourceBlock(
                    block_id="blk-introduction",
                    document_id="paper-1",
                    block_type="paragraph",
                    text=intro_text,
                    block_order=31,
                    page=2,
                    heading_path="1. Introduction",
                ),
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
                "title": "How do laser power and scan speed affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_density",
                    "claim_type": "finding",
                    "statement": "Laser power and scan speed affect density.",
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_results"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_density",
                    "relation_type": "affects",
                    "subject": "laser power and scan speed",
                    "predicate": "affects",
                    "object": "density",
                    "statement": "Laser power and scan speed affect density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_results"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_results",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
                {
                    "evidence_ref_id": "evref_intro_review",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Introduction",
                    "locator": {"source_ref": "blk-introduction"},
                    "fact_ids": ["unit_intro"],
                    "traceability_status": "resolved",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["laser power", "scan speed"],
                    },
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_results"]
    assert finding["evidence_bundle"]["uncategorized"] == []


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
                    "label": "P001 Table 1 relative density",
                    "locator": {"source_ref": "table-1"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "quote": "Relative density increased with laser power.",
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


def test_with_presentation_projects_findings_contract():
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
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_density", "evref_density_text"],
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
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P001 Table 1 relative density",
                    "locator": {"source_ref": "table-1"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "quote": "Relative density increased with laser power.",
                },
                {
                    "evidence_ref_id": "evref_density_text",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_density"],
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
    repeated = service.with_presentation(stored)

    assert understanding is not None
    assert repeated is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["finding_id"] == "finding_claim_density"
    assert repeated["presentation"]["findings"][0]["finding_id"] == finding["finding_id"]
    assert finding["claim_id"] == "claim_density"
    assert finding["title"] == "laser power -> relative density"
    assert finding["statement"] == "Laser power increases relative density."
    assert finding["variables"] == ["laser power"]
    assert finding["mediators"] == []
    assert finding["outcomes"] == ["relative density"]
    assert finding["direction"] == "increases"
    assert finding["scope_summary"] == "316L stainless steel, laser power"
    assert finding["support_grade"] == "partial"
    assert finding["review_status"] == "pending_review"
    assert finding["paper_count"] == 1
    assert finding["evidence_count"] == 2
    assert finding["evidence_ref_ids"] == ["evref_density", "evref_density_text"]
    assert finding["relation_ids"] == ["rel_laser_density"]
    assert finding["evidence_bundle"] == {
        "direct_result": ["evref_density"],
        "mechanism": [],
        "condition_context": [],
        "background": [],
        "conflict": [],
        "noise": [],
        "uncategorized": ["evref_density_text"],
    }


def test_with_presentation_buckets_finding_evidence_by_role():
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
                    "confidence": 0.86,
                    "evidence_ref_ids": [
                        "evref_direct",
                        "evref_mechanism",
                        "evref_background",
                        "evref_unknown",
                    ],
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
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_direct",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P001 Table 1",
                    "locator": {"source_ref": "table-1"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
                {
                    "evidence_ref_id": "evref_mechanism",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Mechanism",
                    "locator": {"source_ref": "blk-mechanism"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "mediator_context",
                },
                {
                    "evidence_ref_id": "evref_background",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Background",
                    "locator": {"source_ref": "blk-background"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "background_context",
                },
                {
                    "evidence_ref_id": "evref_unknown",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Context",
                    "locator": {"source_ref": "blk-context"},
                    "fact_ids": ["unit_density"],
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
    evidence_by_id = {
        ref["evidence_ref_id"]: ref for ref in understanding["evidence_refs"]
    }
    assert evidence_by_id["evref_direct"]["evidence_role"] == "direct_support"
    evidence_item_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    assert evidence_item_by_id["evref_direct"]["evidence_role"] == "direct_support"
    finding = understanding["presentation"]["findings"][0]
    assert finding["evidence_bundle"] == {
        "direct_result": ["evref_direct"],
        "mechanism": ["evref_mechanism"],
        "condition_context": [],
        "background": ["evref_background"],
        "conflict": [],
        "noise": [],
        "uncategorized": ["evref_unknown"],
    }


def test_with_presentation_semantic_match_infers_relation_linked_direct_result():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does preheating affect porosity?",
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_porosity",
                    "claim_type": "finding",
                    "statement": "Build platform preheating decreases porosity.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_relation_text", "evref_context_only"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_relation"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_porosity",
                    "relation_type": "reduces",
                    "subject": "build platform preheating",
                    "predicate": "reduces",
                    "object": "porosity",
                    "statement": "Build platform preheating decreases porosity.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_relation_text"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_relation"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_relation_text",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_relation"],
                    "traceability_status": "resolved",
                    "quote": (
                        "Comparing polished sections, the porosity level "
                        "decreased for specimens fabricated with preheating."
                    ),
                },
                {
                    "evidence_ref_id": "evref_context_only",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Methods",
                    "locator": {"source_ref": "blk-methods"},
                    "fact_ids": ["unit_context"],
                    "traceability_status": "resolved",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "LPBF"},
                    "property_scope": ["porosity"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_relation_text"]
    assert finding["evidence_bundle"]["uncategorized"] == ["evref_context_only"]
    assert finding["support_grade"] == "partial"


def test_with_presentation_semantic_gate_keeps_off_target_evidence_uncategorized():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does porosity affect pitting corrosion?",
            },
            "claims": [
                {
                    "claim_id": "claim_corrosion",
                    "claim_type": "finding",
                    "statement": (
                        "Porosity level and pore size affect pitting corrosion "
                        "behavior."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_density_table"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density_table"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_porosity_corrosion",
                    "relation_type": "increases",
                    "subject": "porosity level and pore size",
                    "predicate": "increases",
                    "object": "pitting corrosion behavior",
                    "statement": (
                        "Porosity level and pore size affect pitting corrosion "
                        "behavior."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density_table"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density_table"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density_table",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P001 Table 3 density and pore size",
                    "locator": {"source_ref": "table-density"},
                    "fact_ids": ["unit_density_table"],
                    "traceability_status": "resolved",
                    "quote": (
                        "Table 3 measured average melt pool and grain sizes, "
                        "and the densities obtained by the Archimedes method."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "SLM"},
                    "property_scope": ["pitting corrosion behavior"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["outcomes"] == ["pitting corrosion behavior"]
    assert finding["evidence_bundle"]["direct_result"] == []
    assert finding["evidence_bundle"]["uncategorized"] == ["evref_density_table"]
    assert finding["support_grade"] == "insufficient"


def test_with_presentation_recalls_target_matching_corrosion_relation_evidence():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does porosity affect pitting corrosion?",
            },
            "claims": [
                {
                    "claim_id": "claim_corrosion",
                    "claim_type": "finding",
                    "statement": (
                        "Porosity level and pore size affect pitting corrosion "
                        "behavior."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_density_table"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density_table"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_porosity_corrosion",
                    "relation_type": "increases",
                    "subject": "porosity level",
                    "predicate": "increases",
                    "object": "pitting corrosion behavior",
                    "statement": (
                        "Higher porosity level increases pitting corrosion "
                        "susceptibility."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": [
                        "evref_density_table",
                        "evref_corrosion_text",
                    ],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": [
                        "unit_density_table",
                        "unit_corrosion_text",
                    ],
                },
                {
                    "relation_id": "rel_slm_porosity",
                    "relation_type": "explains",
                    "subject": "selective laser melting",
                    "predicate": "explains",
                    "object": "porosity",
                    "statement": (
                        "Selective laser melting process parameters affect "
                        "porosity formation."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density_table"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density_table"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density_table",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P001 Table 3 density and pore size",
                    "locator": {"source_ref": "table-density"},
                    "fact_ids": ["unit_density_table"],
                    "traceability_status": "resolved",
                    "quote": (
                        "Table 3 measured average melt pool and grain sizes, "
                        "and the densities obtained by the Archimedes method."
                    ),
                },
                {
                    "evidence_ref_id": "evref_corrosion_text",
                    "source_kind": "text_window",
                    "document_id": "paper-5",
                    "label": "P005 Conclusion",
                    "locator": {"source_ref": "blk-corrosion"},
                    "fact_ids": ["unit_corrosion_text"],
                    "traceability_status": "resolved",
                    "quote": (
                        "Porosities were highly sensitive to pitting corrosion "
                        "behavior, with pores reducing passive film stability."
                    ),
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "SLM"},
                    "property_scope": ["pitting corrosion behavior"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["title"] == "porosity level -> pitting corrosion behavior"
    assert finding["variables"] == ["porosity level"]
    assert finding["outcomes"] == ["pitting corrosion behavior"]
    assert finding["relation_ids"] == ["rel_porosity_corrosion"]
    assert finding["evidence_ref_ids"] == [
        "evref_density_table",
        "evref_corrosion_text",
    ]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_corrosion_text"]
    assert finding["evidence_bundle"]["uncategorized"] == ["evref_density_table"]
    assert finding["support_grade"] == "partial"


def test_with_presentation_keeps_proxy_relations_for_broad_microstructure_targets():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": (
                    "How do laser power and scan speed affect microstructure "
                    "and mechanical properties?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_microstructure",
                    "claim_type": "finding",
                    "statement": (
                        "Laser power and scan speed directly link process "
                        "parameters to defect formation and density improvement."
                    ),
                    "status": "supported",
                    "confidence": 0.8,
                    "evidence_ref_ids": ["evref_pores"],
                    "context_ids": ["ctx_microstructure"],
                    "source_object_ids": ["unit_pores"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_power_porosity",
                    "relation_type": "reduces",
                    "subject": "laser power",
                    "predicate": "reduces",
                    "object": "melt pool dynamics -> porosity",
                    "statement": (
                        "Higher laser power reduces porosity by stabilizing "
                        "melt pool dynamics."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_pores"],
                    "context_ids": ["ctx_microstructure"],
                    "source_object_ids": ["unit_pores"],
                },
                {
                    "relation_id": "rel_lbpf_density",
                    "relation_type": "increases",
                    "subject": "laser beam powder bed fusion",
                    "predicate": "increases",
                    "object": "melt pool stability -> density",
                    "statement": (
                        "Laser beam powder bed fusion changes density "
                        "through melt pool stability."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_pores"],
                    "context_ids": ["ctx_microstructure"],
                    "source_object_ids": ["unit_pores"],
                },
                {
                    "relation_id": "rel_hip_microstructure",
                    "relation_type": "explains",
                    "subject": "hot isostatic pressing",
                    "predicate": "explains",
                    "object": "microstructure",
                    "statement": (
                        "Hot isostatic pressing changes microstructure in "
                        "HIP-SLM samples."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_pores"],
                    "context_ids": ["ctx_microstructure"],
                    "source_object_ids": ["unit_pores"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_pores",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 pore result",
                    "locator": {"source_ref": "blk-pores"},
                    "fact_ids": ["unit_pores"],
                    "traceability_status": "resolved",
                    "quote": (
                        "At higher laser power, pore size decreased and the "
                        "average density increased."
                    ),
                },
                {
                    "evidence_ref_id": "evref_background",
                    "source_kind": "text_window",
                    "document_id": "paper-2",
                    "label": "P002 background",
                    "locator": {"source_ref": "blk-background"},
                    "fact_ids": ["unit_background"],
                    "traceability_status": "resolved",
                    "quote": "The paper describes microstructure after HIP.",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_objective_scope",
                    "label": "Objective scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process": "LPBF",
                        "variable_process_axes": ["laser power"],
                        "process_context_axes": ["laser beam powder bed fusion"],
                    },
                    "property_scope": ["microstructure", "mechanical properties"],
                },
                {
                    "context_id": "ctx_microstructure",
                    "label": "Claim applicability",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "LPBF"},
                    "property_scope": ["microstructure"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["relation_ids"] == [
        "rel_power_porosity",
        "rel_lbpf_density",
    ]
    assert finding["variables"] == ["laser power", "laser beam powder bed fusion"]
    assert finding["outcomes"] == ["porosity", "density"]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_pores"]
    assert finding["support_grade"] == "partial"


def test_with_presentation_recalls_goal_variable_relation_when_claim_is_off_axis():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": (
                    "How does build platform preheating affect "
                    "microstructure?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_off_axis",
                    "claim_type": "finding",
                    "statement": (
                        "Laser power and scan speed affect pore size and "
                        "density."
                    ),
                    "status": "supported",
                    "confidence": 0.8,
                    "evidence_ref_ids": ["evref_scan_speed"],
                    "context_ids": ["ctx_scan_speed"],
                    "source_object_ids": ["unit_scan_speed"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_scan_speed_porosity",
                    "relation_type": "increases",
                    "subject": "scan speed",
                    "predicate": "increases",
                    "object": "porosity",
                    "statement": "Higher scan speed increases porosity.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_scan_speed"],
                    "context_ids": ["ctx_scan_speed"],
                    "source_object_ids": ["unit_scan_speed"],
                },
                {
                    "relation_id": "rel_preheat_microstructure",
                    "relation_type": "improves",
                    "subject": "build platform preheating",
                    "predicate": "improves",
                    "object": "thermal gradients -> microstructure",
                    "statement": (
                        "Build platform preheating improves microstructure by "
                        "reducing thermal gradients."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_preheat"],
                    "source_object_ids": ["unit_preheat"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_scan_speed",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 scan speed",
                    "locator": {"source_ref": "blk-scan"},
                    "fact_ids": ["unit_scan_speed"],
                    "traceability_status": "resolved",
                    "quote": "Scan speed changed pore size and density.",
                },
                {
                    "evidence_ref_id": "evref_preheat",
                    "source_kind": "text_window",
                    "document_id": "paper-2",
                    "label": "P002 preheat",
                    "locator": {"source_ref": "blk-preheat"},
                    "fact_ids": ["unit_preheat"],
                    "traceability_status": "resolved",
                    "quote": (
                        "Build platform preheating reduced thermal gradients "
                        "and changed the microstructure."
                    ),
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_objective_scope",
                    "label": "Objective scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process_context_axes": ["laser beam powder bed fusion"],
                        "variable_process_axes": ["build platform preheating"],
                    },
                    "property_scope": ["microstructure"],
                },
                {
                    "context_id": "ctx_scan_speed",
                    "label": "Claim applicability",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "LPBF"},
                    "property_scope": ["microstructure"],
                },
                {
                    "context_id": "ctx_preheat",
                    "label": "Claim applicability",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "LPBF"},
                    "property_scope": ["microstructure"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    findings = understanding["presentation"]["findings"]
    assert [finding["relation_ids"] for finding in findings] == [
        ["rel_preheat_microstructure"],
        [],
    ]
    assert findings[0]["title"] == "build platform preheating -> microstructure"
    assert findings[0]["variables"] == ["build platform preheating"]
    assert findings[0]["evidence_bundle"]["direct_result"] == ["evref_preheat"]
    assert findings[0]["support_grade"] == "partial"
    assert findings[1]["support_grade"] == "insufficient"


def test_with_presentation_semantic_match_handles_porosity_pore_variants():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does scan speed affect porosity?",
            },
            "claims": [
                {
                    "claim_id": "claim_pores",
                    "claim_type": "finding",
                    "statement": "Scan speed changes porosity.",
                    "status": "supported",
                    "confidence": 0.84,
                    "evidence_ref_ids": ["evref_pores"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_pores"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_speed_porosity",
                    "relation_type": "changes",
                    "subject": "scan speed",
                    "predicate": "changes",
                    "object": "porosity",
                    "statement": "Scan speed changes porosity.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_pores"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_pores"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_pores",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-pores"},
                    "fact_ids": ["unit_pores"],
                    "traceability_status": "resolved",
                    "quote": (
                        "Pores with irregular shapes were observed, and the "
                        "pore size ranged from tens to hundreds of micrometers."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "SLM"},
                    "property_scope": ["porosity"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_pores"]
    assert finding["support_grade"] == "partial"


def test_with_presentation_assigns_support_grade_from_evidence_quality():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does processing affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_strong",
                    "claim_type": "finding",
                    "statement": "Preheating reduces porosity.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_strong_direct", "evref_strong_mechanism"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_strong"],
                },
                {
                    "claim_id": "claim_partial",
                    "claim_type": "finding",
                    "statement": "Laser power increases relative density.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_partial_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_partial"],
                },
                {
                    "claim_id": "claim_weak",
                    "claim_type": "finding",
                    "statement": "Scan speed affects relative density.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_weak_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_weak"],
                },
                {
                    "claim_id": "claim_conflict",
                    "claim_type": "finding",
                    "statement": "Energy density has conflicting density effects.",
                    "status": "conflicted",
                    "confidence": 0.72,
                    "evidence_ref_ids": ["evref_conflict"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_conflict"],
                },
                {
                    "claim_id": "claim_insufficient",
                    "claim_type": "finding",
                    "statement": "Background context suggests possible density effects.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_background"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_insufficient"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_strong",
                    "relation_type": "reduces",
                    "subject": "preheating",
                    "predicate": "reduces",
                    "object": "porosity",
                    "statement": "Preheating reduces porosity.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_strong_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_strong"],
                },
                {
                    "relation_id": "rel_partial",
                    "relation_type": "increases",
                    "subject": "laser power",
                    "predicate": "increases",
                    "object": "relative density",
                    "statement": "Laser power increases relative density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_partial_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_partial"],
                },
                {
                    "relation_id": "rel_conflict",
                    "relation_type": "conflicts",
                    "subject": "energy density",
                    "predicate": "conflicts",
                    "object": "relative density",
                    "statement": "Energy density has conflicting density effects.",
                    "status": "conflicted",
                    "evidence_ref_ids": ["evref_conflict"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_conflict"],
                },
                {
                    "relation_id": "rel_insufficient",
                    "relation_type": "correlates",
                    "subject": "process window",
                    "predicate": "correlates",
                    "object": "relative density",
                    "statement": "Background context suggests possible density effects.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_background"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_insufficient"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_strong_direct",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P001 Table 1",
                    "locator": {"source_ref": "table-1"},
                    "fact_ids": ["unit_strong"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
                {
                    "evidence_ref_id": "evref_strong_mechanism",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Discussion",
                    "locator": {"source_ref": "blk-mechanism"},
                    "fact_ids": ["unit_strong"],
                    "traceability_status": "resolved",
                    "evidence_role": "mediator_context",
                },
                {
                    "evidence_ref_id": "evref_partial_direct",
                    "source_kind": "table",
                    "document_id": "paper-2",
                    "label": "P002 Table 1",
                    "locator": {"source_ref": "table-2"},
                    "fact_ids": ["unit_partial"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
                {
                    "evidence_ref_id": "evref_weak_direct",
                    "source_kind": "table",
                    "document_id": "paper-3",
                    "label": "P003 Table 1",
                    "locator": {"source_ref": "table-3"},
                    "fact_ids": ["unit_weak"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
                {
                    "evidence_ref_id": "evref_conflict",
                    "source_kind": "text_window",
                    "document_id": "paper-4",
                    "label": "P004 Results",
                    "locator": {"source_ref": "blk-conflict"},
                    "fact_ids": ["unit_conflict"],
                    "traceability_status": "resolved",
                    "evidence_role": "conflict",
                },
                {
                    "evidence_ref_id": "evref_background",
                    "source_kind": "text_window",
                    "document_id": "paper-5",
                    "label": "P005 Introduction",
                    "locator": {"source_ref": "blk-background"},
                    "fact_ids": ["unit_insufficient"],
                    "traceability_status": "resolved",
                    "evidence_role": "background_context",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "LPBF"},
                    "property_scope": ["relative density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    grades = {
        finding["claim_id"]: finding["support_grade"]
        for finding in understanding["presentation"]["findings"]
    }
    assert grades == {
        "claim_strong": "strong",
        "claim_partial": "partial",
        "claim_weak": "weak",
        "claim_conflict": "conflict",
        "claim_insufficient": "insufficient",
    }


def test_with_presentation_builds_finding_fields_from_mediated_relation():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does preheating affect porosity?",
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_porosity",
                    "claim_type": "finding",
                    "statement": "Preheating reduces porosity through melt pool stabilization.",
                    "status": "supported",
                    "confidence": 0.88,
                    "evidence_ref_ids": ["evref_direct", "evref_mechanism"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct", "unit_mechanism"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_chain",
                    "relation_type": "reduces",
                    "subject": "preheating",
                    "predicate": "reduces",
                    "object": "melt pool instability -> porosity",
                    "statement": "Preheating reduces porosity through melt pool stabilization.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct", "unit_mechanism"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_direct",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P001 Table 1",
                    "locator": {"source_ref": "table-1"},
                    "fact_ids": ["unit_direct"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
                {
                    "evidence_ref_id": "evref_mechanism",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Discussion",
                    "locator": {"source_ref": "blk-discussion"},
                    "fact_ids": ["unit_mechanism"],
                    "traceability_status": "resolved",
                    "evidence_role": "mediator_context",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "LPBF"},
                    "property_scope": ["porosity"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["variables"] == ["preheating"]
    assert finding["mediators"] == ["melt pool instability"]
    assert finding["outcomes"] == ["porosity"]
    assert finding["direction"] == "reduces"
    assert finding["scope_summary"] == "316L stainless steel, LPBF"
    assert finding["title"] == "preheating -> porosity"
    assert finding["relation_chain"] == [
        {
            "relation_id": "rel_preheat_chain",
            "variable": "preheating",
            "mediators": ["melt pool instability"],
            "outcome": "porosity",
            "direction": "reduces",
            "statement": "Preheating reduces porosity through melt pool stabilization.",
        }
    ]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_direct"]
    assert finding["evidence_bundle"]["mechanism"] == ["evref_mechanism"]


def test_with_presentation_finding_title_uses_relation_outcome_over_context_mediator():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does preheating affect mechanical properties?",
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_mechanical",
                    "claim_type": "finding",
                    "statement": (
                        "Preheating improves mechanical properties through "
                        "microstructure evolution."
                    ),
                    "status": "supported",
                    "confidence": 0.88,
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_mechanical",
                    "relation_type": "improves",
                    "subject": "build platform preheating temperature",
                    "predicate": "improves",
                    "object": "microstructure -> mechanical properties",
                    "statement": (
                        "Higher build platform preheating temperature improves "
                        "mechanical properties by modifying microstructure."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_direct",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Conclusions",
                    "locator": {"source_ref": "blk-conclusion"},
                    "fact_ids": ["unit_direct"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Preheating increased ductility by 14% and this was "
                        "attributed to homogenized microstructure."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "build platform preheating temperature"
                        ]
                    },
                    "property_scope": ["microstructure"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["title"] == (
        "build platform preheating temperature -> mechanical properties"
    )
    assert finding["variables"] == ["build platform preheating temperature"]
    assert finding["mediators"] == ["microstructure"]
    assert finding["outcomes"] == ["mechanical properties"]
    assert finding["relation_chain"] == [
        {
            "relation_id": "rel_preheat_mechanical",
            "variable": "build platform preheating temperature",
            "mediators": ["microstructure"],
            "outcome": "mechanical properties",
            "direction": "improves",
            "statement": (
                "Higher build platform preheating temperature improves "
                "mechanical properties by modifying microstructure."
            ),
        }
    ]


def test_with_presentation_finding_order_prioritizes_expert_usable_rows():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does preheating affect mechanical properties?",
            },
            "claims": [
                {
                    "claim_id": "claim_context_only",
                    "claim_type": "finding",
                    "statement": "Preheating was investigated for LPBF 316L.",
                    "status": "supported",
                    "confidence": 0.84,
                    "evidence_ref_ids": ["evref_context"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_context"],
                },
                {
                    "claim_id": "claim_preheat_mechanical",
                    "claim_type": "finding",
                    "statement": (
                        "Preheating improves mechanical properties through "
                        "microstructure evolution."
                    ),
                    "status": "supported",
                    "confidence": 0.88,
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_mechanical",
                    "relation_type": "improves",
                    "subject": "build platform preheating",
                    "predicate": "improves",
                    "object": "microstructure -> mechanical properties",
                    "statement": (
                        "Build platform preheating improves mechanical "
                        "properties through microstructure evolution."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_context",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Abstract",
                    "locator": {"source_ref": "blk-abstract"},
                    "fact_ids": ["unit_context"],
                    "traceability_status": "resolved",
                    "evidence_role": "background_context",
                },
                {
                    "evidence_ref_id": "evref_direct",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_direct"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "Preheating increased ductility by 14%.",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["build platform preheating"]
                    },
                    "property_scope": ["mechanical properties"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    findings = understanding["presentation"]["findings"]
    assert [finding["claim_id"] for finding in findings] == [
        "claim_preheat_mechanical",
        "claim_context_only",
    ]
    assert findings[0]["support_grade"] == "partial"
    assert findings[0]["evidence_bundle"]["direct_result"] == ["evref_direct"]
    assert findings[1]["support_grade"] == "insufficient"
    assert findings[1]["evidence_bundle"]["background"] == ["evref_context"]
    assert understanding["presentation"]["primary_findings"] == [findings[0]]
    assert understanding["presentation"]["review_queue_findings"] == [findings[1]]
    assert (
        understanding["presentation"]["summary"]["primary_finding_count"]
        == 1
    )
    assert (
        understanding["presentation"]["summary"]["review_queue_finding_count"]
        == 1
    )


def test_with_presentation_concrete_variable_replaces_broad_process_display():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does VED affect microstructure?",
            },
            "claims": [
                {
                    "claim_id": "claim_ved_microstructure",
                    "claim_type": "finding",
                    "statement": (
                        "The increase in VED from medium to high level did "
                        "not notably affect melt pool size or grain size."
                    ),
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_ved"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_ved"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_slm_microstructure",
                    "relation_type": "explains",
                    "subject": "selective laser melting",
                    "predicate": "explains",
                    "object": "microstructure",
                    "statement": (
                        "The increase in VED from medium to high level did "
                        "not notably affect melt pool size or grain size."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_ved"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_ved"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_ved",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_ved"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "The increase in VED from the medium to high level did "
                        "not notably affect the melt pool size or grain size."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "selective laser melting"},
                    "property_scope": ["microstructure"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["variables"] == ["VED"]
    assert finding["title"] == "VED -> microstructure"
    assert finding["relation_chain"][0]["variable"] == "selective laser melting"


def test_with_presentation_concrete_variable_keeps_specific_process_variable():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does preheating affect properties?",
            },
            "claims": [
                {
                    "claim_id": "claim_preheat",
                    "claim_type": "finding",
                    "statement": "Preheating improves mechanical properties.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat",
                    "relation_type": "improves",
                    "subject": "build platform preheating temperature",
                    "predicate": "improves",
                    "object": "mechanical properties",
                    "statement": "Preheating improves mechanical properties.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_preheat",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_preheat"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "Preheating temperature increased ductility by 14%.",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "build platform preheating temperature"
                        ]
                    },
                    "property_scope": ["mechanical properties"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["variables"] == ["build platform preheating temperature"]
    assert finding["title"] == (
        "build platform preheating temperature -> mechanical properties"
    )


def test_with_presentation_drops_placeholder_relation_chain_segments():
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
                    "claim_type": "finding",
                    "statement": "LPBF affects relative density.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_noisy",
                    "relation_type": "correlates",
                    "subject": "None",
                    "predicate": "correlates",
                    "object": "None -> relative density",
                    "statement": "LPBF affects relative density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
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
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "LPBF"},
                    "property_scope": ["relative density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    effect = understanding["presentation"]["effects"][0]
    assert effect["relation_ids"] == []
    finding = understanding["presentation"]["findings"][0]
    assert finding["variables"] == ["LPBF"]
    assert finding["mediators"] == []
    assert finding["outcomes"] == ["relative density"]


def test_with_presentation_finding_fields_fall_back_without_relation():
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
                    "claim_type": "measurement",
                    "statement": "Relative density is reported as 99.1%.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_density"],
                    "source_object_ids": ["unit_density"],
                }
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
                }
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
    finding = understanding["presentation"]["findings"][0]
    assert finding["variables"] == ["LPBF"]
    assert finding["mediators"] == []
    assert finding["outcomes"] == ["relative density"]
    assert finding["direction"] == ""


def test_with_presentation_projects_empty_findings_without_claims():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())

    understanding = service.with_presentation(
        ResearchUnderstanding.from_mapping(
            {
                "state": "empty",
                "scope": {
                    "scope_type": "goal",
                    "collection_id": "col-1",
                    "goal_id": "goal-1",
                    "title": "No findings yet",
                },
            }
        )
    )

    assert understanding is not None
    assert understanding["presentation"]["effects"] == []
    assert understanding["presentation"]["findings"] == []


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
