from __future__ import annotations

import json

from application.core import research_understanding_service as understanding_module
from application.core.research_understanding_service import (
    ResearchUnderstandingService,
)
from controllers.schemas.core.research_understanding import (
    ResearchUnderstandingResponse,
)
from domain.core import ResearchUnderstanding
from domain.source import SourceBlock, SourceDocument, SourceTable


class _FakeSourceArtifactRepository:
    def __init__(
        self,
        *,
        blocks: list[SourceBlock] | None = None,
        documents: list[SourceDocument] | None = None,
        tables: list[SourceTable] | None = None,
    ) -> None:
        self.blocks = blocks or []
        self.documents = documents or []
        self.tables = tables or []

    def list_blocks(self, collection_id: str) -> list[SourceBlock]:
        return self.blocks

    def list_documents(self, collection_id: str) -> list[SourceDocument]:
        return self.documents

    def list_tables(self, collection_id: str) -> list[SourceTable]:
        return self.tables


class _FakeSemanticExtractor:
    def __init__(
        self,
        relations: list[dict] | None = None,
        trace: dict | None = None,
    ) -> None:
        self.relations = relations or []
        self.trace = trace
        self.payloads: list[dict] = []

    def extract_research_understanding_relations(self, payload: dict):
        self.payloads.append(payload)
        return _FakeSemanticRelations(self.relations)

    def consume_last_trace(self):
        trace = self.trace
        self.trace = None
        return trace


class _FailingSemanticExtractor:
    def __init__(self, trace: dict | None = None) -> None:
        self.trace = trace

    def extract_research_understanding_relations(self, payload: dict):
        raise RuntimeError("relation extractor unavailable")

    def consume_last_trace(self):
        trace = self.trace
        self.trace = None
        return trace


class _FakeSemanticRelations:
    def __init__(self, relations: list[dict]) -> None:
        self.relations = [_FakeSemanticRelation(item) for item in relations]


class _FakeSemanticRelation:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def model_dump(self) -> dict:
        return dict(self.payload)


def _presentation_finding_by_title(
    understanding: dict,
    title: str,
) -> dict:
    return next(
        finding
        for finding in understanding["presentation"]["findings"]
        if finding["title"] == title
    )


def _presentation_finding_by_claim_id(
    understanding: dict,
    claim_id: str,
) -> dict:
    return next(
        finding
        for finding in understanding["presentation"]["findings"]
        if finding["claim_id"] == claim_id
    )


def _presentation_review_finding_by_claim_id(
    understanding: dict,
    claim_id: str,
) -> dict:
    return next(
        finding
        for finding in understanding["presentation"]["review_queue_findings"]
        if finding["claim_id"] == claim_id
    )


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
    assert "semantic_relation" in understanding["relations"][0]["warnings"]
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
    assert presentation["summary"]["review_queue_count"] == 0
    assert presentation["effects"][0]["claim_id"] == understanding["claims"][0]["claim_id"]
    assert presentation["effects"][0]["target_property"] == "corrosion resistance"
    assert presentation["effects"][0]["evidence_count"] == 1
    assert presentation["effects"][0]["needs_review"] is True
    assert presentation["evidence_items"][0]["title"] == "table-1"


def test_objective_understanding_persists_relation_model_trace():
    extractor = _FakeSemanticExtractor(
        relations=[],
        trace={
            "task_type": "research_understanding_relation",
            "prompt_version": "research_understanding_relation.v1",
            "model": "fake-model",
            "trace_status": "available",
            "messages": [{"role": "user", "content": "Input JSON: ..."}],
            "raw_output": "{\"relations\":[]}",
            "parsed_output": {"relations": []},
        },
    )
    service = ResearchUnderstandingService(structured_extractor=extractor)

    understanding = service.build_objective_understanding(_oversized_relation_payload(4))

    ResearchUnderstanding.from_mapping(understanding)
    trace = understanding["model_traces"][0]
    assert trace["trace_id"].startswith("rut_")
    assert trace["task_type"] == "research_understanding_relation"
    assert trace["prompt_version"] == "research_understanding_relation.v1"
    assert trace["model"] == "fake-model"
    assert trace["trace_status"] == "available"
    assert trace["scope_type"] == "objective"
    assert trace["scope_id"] == "obj-density"
    assert trace["input_blocks"][0] == {
        "source_object_id": "oeu-density-0",
        "source_kind": "objective_evidence_unit",
    }
    assert set(trace["source_object_ids"]) == {
        "oeu-density-0",
        "oeu-density-1",
        "oeu-density-2",
        "oeu-density-3",
    }
    assert "api_key" not in json.dumps(trace, ensure_ascii=False).lower()


def test_objective_understanding_persists_failed_relation_model_trace():
    extractor = _FailingSemanticExtractor(
        {
            "task_type": "research_understanding_relation",
            "prompt_version": "research_understanding_relation.v1",
            "model": "fake-model",
            "trace_status": "failed",
            "error": "structured extraction failed",
        }
    )
    service = ResearchUnderstandingService(structured_extractor=extractor)

    understanding = service.build_objective_understanding(_oversized_relation_payload(4))

    assert "relation_extraction_failed" in understanding["warnings"]
    trace = understanding["model_traces"][0]
    assert trace["trace_status"] == "failed"
    assert trace["error"] == "structured extraction failed"
    assert set(trace["source_object_ids"]) == {
        "oeu-density-0",
        "oeu-density-1",
        "oeu-density-2",
        "oeu-density-3",
    }


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


def test_objective_understanding_projects_pairwise_comparison_as_finding():
    payload = _oversized_relation_payload(unit_count=4)
    payload["objective"] = {
        "objective_id": "obj-mechanics",
        "question": (
            "How do scanning strategy, scanning speed, and energy density affect "
            "yield strength?"
        ),
        "material_scope": ["316L stainless steel"],
        "process_axes": ["scanning strategy", "scanning speed", "energy density"],
        "property_axes": ["yield strength"],
    }
    payload["objective_context"] = {
        "objective_id": "obj-mechanics",
        "question": payload["objective"]["question"],
        "material_scope": ["316L stainless steel"],
        "variable_process_axes": [
            "scanning strategy",
            "scanning speed",
            "energy density",
        ],
        "target_property_axes": ["yield strength"],
    }
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-scan-strategy-yield",
            "document_id": "paper-1",
            "unit_kind": "comparison",
            "property_normalized": "yield strength",
            "sample_context": {
                "Condition number": "6",
                "Sample number": "14",
            },
            "process_context": {
                "Energy density (J/mm 3 )": "150",
                "Scan strategy": "A",
                "Scanning speed (mm/s)": "0.111",
            },
            "baseline_context": {
                "process_context": {
                    "Energy density (J/mm 3 )": "150",
                    "Scan strategy": "B",
                    "Scanning speed (mm/s)": "0.111",
                },
                "sample_context": {"Sample number": "15"},
                "source_value_text": "278.76",
                "value": 278.76,
            },
            "value_payload": {
                "comparison_axis": "scanning strategy",
                "controlled_axes": [
                    {"axis": "energy density", "value": "150"},
                    {"axis": "scanning speed", "value": "0.111"},
                ],
                "current_value": 462.02,
                "direction": "increase",
                "source_value_text": "462.02",
                "value": 462.02,
            },
            "unit": "MPa",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-mechanics",
                    "display_label": "P001 Table 2",
                    "role": "current_experimental_evidence",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.91,
        }
    ]
    payload["logic_chain"] = {
        "evidence_unit_ids": ["oeu-scan-strategy-yield"],
        "summary": "",
    }
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            tables=[
                SourceTable(
                    table_id="table-process",
                    document_id="paper-1",
                    table_order=1,
                    page=2,
                    caption_text="Table 1 SLM processing parameters.",
                    caption_block_id=None,
                    bbox=None,
                    heading_path="Experimental procedure",
                    column_headers=(
                        "Condition number",
                        "Sample number",
                        "Hatch space (mm)",
                        "Scan strategy",
                        "Scanning speed (mm/s)",
                        "Energy density (J/mm 3)",
                        "Relative density",
                    ),
                    table_matrix=(
                        ("6", "14", "0.12", "A", "0.111", "150", "99.45"),
                        ("6", "15", "0.12", "B", "0.111", "150", "96.7"),
                    ),
                ),
            ]
        ),
    )

    understanding = service.build_objective_understanding(payload)

    ResearchUnderstanding.from_mapping(understanding)
    claim = understanding["claims"][0]
    relation = understanding["relations"][0]
    assert claim["claim_type"] == "comparison"
    assert claim["statement"] == (
        "Under energy density 150 and scanning speed 0.111, scanning strategy A "
        "increased yield strength from 278.76 MPa (scanning strategy B) to "
        "462.02 MPa."
    )
    assert "is reported as" not in claim["statement"]
    assert relation["subject"] == "scanning strategy"
    assert relation["predicate"] == "increases"
    assert relation["object"] == "yield strength"
    assert relation["relation_type"] == "increases"
    assert relation["statement"] == claim["statement"]
    evidence_by_id = {
        ref["evidence_ref_id"]: ref for ref in understanding["evidence_refs"]
    }
    condition_refs = [
        ref
        for ref in evidence_by_id.values()
        if ref["evidence_role"] == "condition_context"
    ]
    assert len(condition_refs) == 1
    condition_ref = condition_refs[0]
    assert condition_ref["locator"]["source_ref"] == "table-process"
    assert "Sample number: 14" in condition_ref["quote"]
    assert "Scan strategy: A" in condition_ref["quote"]
    assert "Sample number: 15" in condition_ref["quote"]
    assert "Scan strategy: B" in condition_ref["quote"]
    assert set(relation["evidence_ref_ids"]) == {
        next(
            ref_id
            for ref_id, ref in evidence_by_id.items()
            if ref["evidence_role"] == "direct_support"
        ),
        condition_ref["evidence_ref_id"],
    }
    assert understanding["presentation"]["findings"][0]["title"] == (
        "scanning strategy -> yield strength"
    )
    assert understanding["presentation"]["summary"]["primary_finding_count"] == 0
    review_finding = _presentation_review_finding_by_claim_id(
        understanding,
        claim["claim_id"],
    )
    assert review_finding["title"] == "scanning strategy -> yield strength"
    assert review_finding["dataset_use_status"] == "review_candidate"
    assert review_finding["evidence_bundle"]["condition_context"] == [
        condition_ref["evidence_ref_id"]
    ]

    persisted = json.loads(json.dumps(understanding))
    persisted["evidence_refs"] = [
        ref
        for ref in persisted["evidence_refs"]
        if ref["evidence_ref_id"] != condition_ref["evidence_ref_id"]
    ]
    for item in [*persisted["claims"], *persisted["relations"]]:
        item["evidence_ref_ids"] = [
            ref_id
            for ref_id in item["evidence_ref_ids"]
            if ref_id != condition_ref["evidence_ref_id"]
        ]

    reprojected = service.with_presentation(persisted)

    assert reprojected is not None
    reprojected_condition_refs = [
        ref
        for ref in reprojected["evidence_refs"]
        if ref["evidence_role"] == "condition_context"
    ]
    assert len(reprojected_condition_refs) == 1
    reprojected_finding = _presentation_review_finding_by_claim_id(
        reprojected,
        claim["claim_id"],
    )
    assert reprojected_finding["evidence_bundle"]["condition_context"] == [
        reprojected_condition_refs[0]["evidence_ref_id"]
    ]


def test_objective_understanding_presents_symbol_axis_as_material_variable():
    payload = _oversized_relation_payload(unit_count=4)
    payload["objective"] = {
        "objective_id": "obj-texture-yield",
        "question": (
            "How do scan strategy rotation angle and build orientation angle "
            "affect crystallographic texture and yield strength?"
        ),
        "material_scope": ["316L stainless steel"],
        "process_axes": ["scan strategy rotation angle", "build orientation angle"],
        "property_axes": ["crystallographic texture", "yield strength"],
    }
    payload["objective_context"] = {
        "objective_id": "obj-texture-yield",
        "question": payload["objective"]["question"],
        "material_scope": ["316L stainless steel"],
        "variable_process_axes": [
            "scan strategy rotation angle",
            "build orientation angle",
        ],
        "target_property_axes": ["crystallographic texture", "yield strength"],
    }
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-beta-yield",
            "document_id": "paper-6",
            "unit_kind": "comparison",
            "property_normalized": "yield strength prediction",
            "process_context": {"β": "90", "α": "0", "ɵ": "0", "θ": "0"},
            "baseline_context": {
                "process_context": {"β": "0", "α": "0", "ɵ": "0", "θ": "0"},
                "sample_context": {"case": "1"},
                "source_value_text": "310.48",
                "value": 310.48,
            },
            "value_payload": {
                "comparison_axis": "β",
                "controlled_axes": [
                    {"axis": "ɵ", "value": "0"},
                    {"axis": "α", "value": "0"},
                    {"axis": "θ", "value": "0"},
                ],
                "current_value": 314.37,
                "direction": "increase",
                "source_value_text": "314.37",
                "value": 314.37,
            },
            "unit": "MPa",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-texture-yield",
                    "display_label": "P006 Table 2",
                    "role": "current_experimental_evidence",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.91,
        }
    ]
    payload["logic_chain"] = {
        "evidence_unit_ids": ["oeu-beta-yield"],
        "summary": "",
    }
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())

    understanding = service.build_objective_understanding(payload)

    primary = understanding["presentation"]["primary_findings"]
    review_queue = understanding["presentation"]["review_queue_findings"]
    assert primary == []
    assert review_queue == []
    assert understanding["relations"][0]["subject"] == "β build orientation angle"


def test_objective_understanding_table_evidence_quote_includes_relevant_rows():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-preheat",
                    human_readable_id=2,
                    title="Effect of Preheating Build Platform on LPBF 316L",
                    text="",
                )
            ],
            tables=[
                SourceTable(
                    table_id="table-preheat",
                    document_id="paper-preheat",
                    table_order=2,
                    page=8,
                    caption_text=(
                        "Table 2. Monotonic tensile properties of 316L SS "
                        "fabricated in both non-preheated and preheated build "
                        "platform conditions."
                    ),
                    caption_block_id=None,
                    bbox=None,
                    heading_path="Results",
                    column_headers=[
                        "Build platform conditions",
                        "ı y (MPa)",
                        "ı u (MPa)",
                        "El%",
                    ],
                    table_matrix=[
                        ["Build platform conditions", "ı y (MPa)", "ı u (MPa)", "El%"],
                        ["Aged", "430", "590", "61"],
                        ["Non-preheated", "448", "617", "72"],
                        ["Preheated", "465", "618", "82"],
                    ],
                )
            ],
        ),
    )
    payload = _oversized_relation_payload(unit_count=4)
    payload["collection_id"] = "col-preheat"
    payload["objective"] = {
        "objective_id": "obj-preheat",
        "question": "How does preheating affect tensile properties?",
        "material_scope": ["316L stainless steel"],
        "process_axes": ["build platform preheating temperature"],
        "property_axes": ["elongation"],
    }
    payload["objective_context"] = {
        "objective_id": "obj-preheat",
        "question": payload["objective"]["question"],
        "material_scope": ["316L stainless steel"],
        "variable_process_axes": ["build platform preheating temperature"],
        "target_property_axes": ["elongation"],
    }
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-preheat-elongation",
            "document_id": "paper-preheat",
            "unit_kind": "comparison",
            "property_normalized": "elongation",
            "process_context": {"Build platform conditions": "Preheated"},
            "baseline_context": {
                "process_context": {"Build platform conditions": "Non-preheated"},
                "sample_context": {"sample_number": "1"},
                "source_value_text": "72",
                "value": 72,
            },
            "value_payload": {
                "comparison_axis": "build platform preheating temperature",
                "current_value": 82,
                "direction": "increase",
                "source_value_text": "82",
                "value": 82,
            },
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-preheat",
                    "role": "current_experimental_evidence",
                    "evidence_role": "direct_support",
                    "page": 8,
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.91,
        }
    ]
    payload["logic_chain"] = {
        "evidence_unit_ids": ["oeu-preheat-elongation"],
        "summary": "",
    }

    understanding = service.build_objective_understanding(payload)

    evidence_ref = understanding["evidence_refs"][0]
    assert evidence_ref["locator"]["page"] == 8
    assert evidence_ref["href"].startswith(
        "/collections/col-preheat/documents/paper-preheat?"
    )
    assert "source_ref=table-preheat" in evidence_ref["href"]
    assert "Non-preheated | 448 | 617 | 72" in evidence_ref["quote"]
    assert "Preheated | 465 | 618 | 82" in evidence_ref["quote"]
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert (
        "Build platform conditions: Non-preheated; ı y (MPa): 448; "
        "ı u (MPa): 617; El%: 72"
    ) in evidence_item["quote"]
    assert (
        "Build platform conditions: Preheated; ı y (MPa): 465; "
        "ı u (MPa): 618; El%: 82"
    ) in evidence_item["quote"]
    assert "Relevant rows:" in evidence_item["quote"]
    assert "Build platform conditions: Aged" not in evidence_item["quote"]
    assert "Aged | 430 | 590 | 61" in evidence_item["source_text"]
    assert evidence_item["table_audit"]["columns"] == [
        "Build platform conditions",
        "ı y (MPa)",
        "ı u (MPa)",
        "El%",
    ]
    assert evidence_item["table_audit"]["relevant_rows"] == [
        {
            "row_index": 2,
            "cells": ["Non-preheated", "448", "617", "72"],
            "aligned": True,
        },
        {
            "row_index": 3,
            "cells": ["Preheated", "465", "618", "82"],
            "aligned": True,
        },
    ]


def test_objective_understanding_prioritizes_comparison_over_measurement_limit():
    measurement_units = [
        {
            "evidence_unit_id": f"oeu-measurement-{index}",
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "yield strength",
            "sample_context": {"case": str(index)},
            "process_context": {"Scan strategy": "A"},
            "value_payload": {
                "source_value_text": str(300 + index),
                "value": 300 + index,
            },
            "unit": "MPa",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-mechanics",
                    "display_label": "P001 Table 2",
                    "role": "current_experimental_evidence",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.75,
        }
        for index in range(12)
    ]
    payload = _oversized_relation_payload(unit_count=4)
    payload["objective"] = {
        "objective_id": "obj-mechanics",
        "question": "How does scanning strategy affect yield strength?",
        "material_scope": ["316L stainless steel"],
        "process_axes": ["scanning strategy"],
        "property_axes": ["yield strength"],
    }
    payload["objective_context"] = {
        "objective_id": "obj-mechanics",
        "question": payload["objective"]["question"],
        "material_scope": ["316L stainless steel"],
        "variable_process_axes": ["scanning strategy"],
        "target_property_axes": ["yield strength"],
    }
    payload["evidence_units"] = [
        *measurement_units,
        {
            "evidence_unit_id": "oeu-comparison-yield",
            "document_id": "paper-1",
            "unit_kind": "comparison",
            "property_normalized": "yield strength",
            "process_context": {"Scan strategy": "A"},
            "baseline_context": {
                "process_context": {"Scan strategy": "B"},
                "sample_context": {"case": "B"},
                "source_value_text": "278.76",
                "value": 278.76,
            },
            "value_payload": {
                "comparison_axis": "scanning strategy",
                "current_value": 462.02,
                "direction": "increase",
                "source_value_text": "462.02",
                "value": 462.02,
            },
            "unit": "MPa",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-mechanics",
                    "display_label": "P001 Table 2",
                    "role": "current_experimental_evidence",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.91,
        },
    ]
    payload["logic_chain"] = {
        "evidence_unit_ids": [
            *(unit["evidence_unit_id"] for unit in measurement_units),
            "oeu-comparison-yield",
        ],
        "summary": "",
    }
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())

    understanding = service.build_objective_understanding(payload)

    assert understanding["claims"][0]["source_object_ids"] == ["oeu-comparison-yield"]
    assert understanding["claims"][0]["claim_type"] == "comparison"
    assert understanding["relations"][0]["subject"] == "scanning strategy"
    assert understanding["presentation"]["primary_findings"][0]["title"] == (
        "scanning strategy -> yield strength"
    )


def test_objective_understanding_projects_density_effect_relation_from_statement():
    payload = _oversized_relation_payload(unit_count=4)
    payload["objective"]["question"] = "How does heat treatment affect density?"
    payload["objective"]["process_axes"] = ["heat treatment"]
    payload["objective"]["property_axes"] = ["density"]
    payload["objective_context"]["question"] = payload["objective"]["question"]
    payload["objective_context"]["variable_process_axes"] = ["heat treatment"]
    payload["objective_context"]["target_property_axes"] = ["density"]
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


def test_objective_understanding_filters_generic_process_family_relations():
    payload = _oversized_relation_payload(unit_count=4)
    payload["objective"]["question"] = (
        "How do laser power and scan speed affect density and microstructure?"
    )
    payload["objective"]["property_axes"] = ["density", "microstructure"]
    payload["objective_context"]["question"] = payload["objective"]["question"]
    payload["objective_context"]["target_property_axes"] = [
        "density",
        "microstructure",
    ]
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-generic-lpbf",
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "microstructure",
            "process_context": {"process": "laser beam powder bed fusion"},
            "value_payload": {
                "summary": (
                    "The density measurement shows a high level of density for "
                    "the sample fabricated under the specified energy input "
                    "density condition."
                ),
            },
            "interpretation": (
                "The density measurement shows a high level of density for the "
                "sample fabricated under the specified energy input density "
                "condition."
            ),
            "source_refs": [
                {
                    "source_kind": "paragraph",
                    "source_ref": "blk-generic-lpbf",
                    "display_label": "P001 Results",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.78,
        },
        {
            "evidence_unit_id": "oeu-scan-speed-density",
            "document_id": "paper-1",
            "unit_kind": "comparison",
            "property_normalized": "density",
            "value_payload": {
                "comparison_axis": "scan speed",
                "direction": "increases",
                "source_value_text": "scan speed increases density",
            },
            "source_refs": [
                {
                    "source_kind": "paragraph",
                    "source_ref": "blk-density",
                    "display_label": "P001 Results",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.87,
        },
    ]
    payload["logic_chain"]["summary"] = ""
    payload["logic_chain"]["evidence_unit_ids"] = [
        "oeu-generic-lpbf",
        "oeu-scan-speed-density",
    ]
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())

    understanding = service.build_objective_understanding(payload)

    assert [relation["source_object_ids"] for relation in understanding["relations"]] == [
        ["oeu-scan-speed-density"]
    ]
    relation = understanding["relations"][0]
    assert relation["subject"] == "scan speed"
    assert relation["object"] == "density"


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


def test_objective_understanding_promotes_preheating_process_result_to_primary_finding():
    source_text = (
        "Monotonic tensile deformation behavior of specimens fabricated with and "
        "without preheating the build platform is shown in Figure 5. "
        "Interestingly, preheating the build plate increased the El% and yield "
        "strength of the material by approximately 14% and 4%, respectively. "
        "This is attributed to the microstructure and texture evolution."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-preheat",
                    human_readable_id=2,
                    title="Effect of Preheating Build Platform on LPBF 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-preheat-result",
                    document_id="paper-preheat",
                    block_type="paragraph",
                    text=source_text,
                    block_order=136,
                    page=7,
                    heading_path="Tensile properties",
                )
            ],
        ),
    )
    payload = {
        "collection_id": "col-preheat",
        "objective": {
            "objective_id": "obj-preheat",
            "question": (
                "How does build platform preheating affect microstructure and "
                "mechanical properties of 316L stainless steel?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": ["build platform preheating temperature"],
            "property_axes": ["microstructure", "mechanical properties"],
        },
        "objective_context": {
            "objective_id": "obj-preheat",
            "question": (
                "How does build platform preheating affect microstructure and "
                "mechanical properties of 316L stainless steel?"
            ),
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["build platform preheating temperature"],
            "target_property_axes": ["microstructure", "mechanical properties"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-preheat-ductility",
                "document_id": "paper-preheat",
                "unit_kind": "process_context",
                "property_normalized": "mechanical properties",
                "material_system": {"material": "316L stainless steel"},
                "process_context": {
                    "process": "laser beam powder bed fusion",
                    "variable": "build platform preheating temperature",
                },
                "sample_context": {
                    "condition": "with and without preheating the build platform"
                },
                "test_condition": {"test": "tensile properties"},
                "value_payload": {
                    "property": "elongation to failure",
                    "trend": "increased",
                    "value": "14% increase",
                },
                "interpretation": (
                    "attributed to microstructure and texture evolution"
                ),
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "blk-preheat-result",
                        "role": "current_experimental_evidence",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        ],
        "logic_chain": {
            "evidence_unit_ids": ["oeu-preheat-ductility"],
            "summary": "",
        },
    }

    understanding = service.build_objective_understanding(payload)

    assert understanding["claims"][0]["statement"] == (
        "Build platform preheating temperature increased elongation to failure "
        "by 14%."
    )
    assert understanding["relations"][0]["subject"] == (
        "build platform preheating temperature"
    )
    assert understanding["relations"][0]["predicate"] == "increases"
    finding = understanding["presentation"]["primary_findings"][0]
    assert finding["title"] == "build platform preheating temperature -> ductility"
    assert finding["support_grade"] == "partial"
    assert "direct_result" in finding["evidence_bundle"]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    evidence_item = evidence_by_id[finding["evidence_ref_ids"][0]]
    assert evidence_item["title"] == "Effect of Preheating Build Platform on LPBF 316L / p. 7"
    assert "preheating the build plate increased the El%" in evidence_item["quote"]


def test_objective_understanding_keeps_scan_speed_tensile_finding_in_review_queue_without_table():
    scope_text = (
        "SLM processing parameters including scanning strategy, scanning speed, "
        "and energy density have significant effects on densification, "
        "microstructure, and mechanical properties of 316L stainless steel."
    )
    conclusion_text = (
        "\ufffd The  SLM  samples  processed  at  higher  scanning  speed "
        "exhibited better densification, refined microstructure, and excellent "
        "mechanical properties, owing to higher cooling rate. With lower "
        "scanning speed, the dendrites became wider because of the lower "
        "cooling rate."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FailingSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-slm",
                    human_readable_id=1,
                    title=(
                        "Selective laser melting parameters and mechanical "
                        "properties of 316L"
                    ),
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-slm-scope",
                    document_id="paper-slm",
                    block_type="paragraph",
                    text=scope_text,
                    block_order=111,
                    page=12,
                    heading_path="Conclusions",
                ),
                SourceBlock(
                    block_id="blk-slm-conclusion",
                    document_id="paper-slm",
                    block_type="paragraph",
                    text=conclusion_text,
                    block_order=115,
                    page=12,
                    heading_path="Conclusions",
                )
            ],
        ),
    )
    payload = {
        "collection_id": "col-slm",
        "objective": {
            "objective_id": "obj-slm",
            "question": (
                "How do scanning strategy, scanning speed, and energy density "
                "affect yield strength, ultimate tensile strength, and "
                "elongation of 316L stainless steel processed via selective "
                "laser melting?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": [
                "scanning strategy",
                "scanning speed",
                "energy density",
            ],
            "property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
        },
        "objective_context": {
            "objective_id": "obj-slm",
            "question": (
                "How do scanning strategy, scanning speed, and energy density "
                "affect yield strength, ultimate tensile strength, and "
                "elongation of 316L stainless steel processed via selective "
                "laser melting?"
            ),
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": [
                "scanning strategy",
                "scanning speed",
                "energy density",
            ],
            "target_property_axes": [
                "yield strength",
                "ultimate tensile strength",
                "elongation",
            ],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-scan-speed",
                "document_id": "paper-slm",
                "unit_kind": "comparison",
                "property_normalized": "mechanical properties",
                "material_system": {"material": "316L stainless steel"},
                "process_context": {
                    "process": "selective laser melting",
                    "scanning_speed": "higher scanning speed",
                    "energy_density": "150 J/mm3",
                },
                "sample_context": {"condition": "SLM 316L tensile sample"},
                "test_condition": {"test": "tensile properties"},
                "value_payload": {
                    "trend": "improved",
                    "summary": (
                        "higher scanning speed improves mechanical properties"
                    ),
                },
                "interpretation": (
                    "higher cooling rate refines microstructure and improves "
                    "mechanical properties"
                ),
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "blk-slm-conclusion",
                        "role": "current_experimental_evidence",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.91,
            }
        ],
        "logic_chain": {
            "evidence_unit_ids": ["oeu-scan-speed"],
            "summary": "",
        },
    }

    understanding = service.build_objective_understanding(payload)

    primary = understanding["presentation"]["primary_findings"]
    assert primary == []
    review_queue = understanding["presentation"]["review_queue_findings"]
    assert review_queue
    finding = next(
        item
        for item in review_queue
        if item["claim_id"].startswith("claim_recovered_scan_speed")
    )
    assert finding["claim_id"].startswith("claim_recovered_scan_speed")
    assert finding["title"] == "scanning speed -> densification, microstructure, and mechanical properties"
    assert finding["outcomes"] == [
        "densification",
        "microstructure",
        "mechanical properties",
    ]
    assert finding["evidence_bundle"]["direct_result"] == [
        "evref_recovered_scan_speed_density_microstructure_blk-slm-conclusion"
    ]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    evidence_item = evidence_by_id[
        "evref_recovered_scan_speed_density_microstructure_blk-slm-conclusion"
    ]
    assert evidence_item["source_ref"] == "blk-slm-conclusion"
    assert evidence_item["page"] == "12"
    assert "higher scanning speed exhibited better densification" in evidence_item["quote"]
    assert "\ufffd" not in evidence_item["quote"]
    assert "\ufffd" not in evidence_item["source_text"]
    review_titles = [
        item["title"]
        for item in understanding["presentation"]["review_queue_findings"]
    ]
    assert "SLM processing parameters -> mechanical properties" not in review_titles
    assert all(
        "is associated with mechanical properties" not in item["statement"]
        for item in understanding["presentation"]["review_queue_findings"]
    )


def test_with_presentation_uses_goal_title_as_recovered_finding_boundary():
    preheat_text = (
        "Preheating the build platform to 150 C increased the ductility of "
        "material by 14%. This is attributed to the more homogenized "
        "microstructure as well as cellular structure with geometry necessary "
        "dislocations (GNDs), thereby material accommodated more plastic "
        "strains during deformation."
    )
    heat_text = (
        "Microstructure: It was confirmed that the heat treatments of the SLM "
        "samples induced an increase in the density. The cellular "
        "microstructure and dense dislocation structures of the as-SLM "
        "disappeared after the short heat treatments owing to recrystallization. "
        "Mechanical properties: The decrease in hardness and tensile strength "
        "and the increase in elongation after the heat treatments were "
        "attributed to the reduction in the dislocation density and cellular "
        "microstructures."
    )
    scan_speed_text = (
        "The SLM samples processed at higher scanning speed exhibited better "
        "densification, refined microstructure, and excellent mechanical "
        "properties as compared to samples processed with lower scanning "
        "speed."
    )
    fatigue_text = (
        "The present results indicate that the increasing VED leads to lower "
        "fraction of defects, slightly smaller defect size and complexity, and "
        "improves slightly the fatigue life. The fatigue limit is still "
        "limited by remaining LoF defects."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-preheat",
                    human_readable_id=2,
                    title="Preheating effects in LPBF 316L",
                    text="",
                ),
                SourceDocument(
                    document_id="paper-heat",
                    human_readable_id=4,
                    title="Heat treatment effect on SLM 316L",
                    text="",
                ),
                SourceDocument(
                    document_id="paper-scan",
                    human_readable_id=1,
                    title="Scan speed effects on SLM 316L",
                    text="",
                ),
                SourceDocument(
                    document_id="paper-fatigue",
                    human_readable_id=3,
                    title="VED effects on defect structure and fatigue behaviour",
                    text="",
                ),
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-preheat-conclusion",
                    document_id="paper-preheat",
                    block_type="list_item",
                    text=preheat_text,
                    block_order=240,
                    page=9,
                    heading_path="Conclusions",
                ),
                SourceBlock(
                    block_id="blk-heat-conclusion",
                    document_id="paper-heat",
                    block_type="list_item",
                    text=heat_text,
                    block_order=133,
                    page=12,
                    heading_path="4. Conclusion",
                ),
                SourceBlock(
                    block_id="blk-scan-conclusion",
                    document_id="paper-scan",
                    block_type="paragraph",
                    text=scan_speed_text,
                    block_order=115,
                    page=12,
                    heading_path="4. Conclusions",
                ),
                SourceBlock(
                    block_id="blk-fatigue-result",
                    document_id="paper-fatigue",
                    block_type="paragraph",
                    text=fatigue_text,
                    block_order=139,
                    page=10,
                    heading_path="4.2. The influence of defect structure on fatigue strength",
                ),
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "limited",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-heat",
                "goal_id": "goal-heat",
                "title": (
                    "How do laser power, scan speed, heat treatment type, "
                    "heat treatment parameters, selective laser melting, and "
                    "heat treatment affect density and microstructure of "
                    "stainless steel 316L?"
                ),
            },
            "claims": [],
            "relations": [],
            "evidence_refs": [],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "variable_process_axes": ["heat treatment"]
                    },
                    "property_scope": ["density", "microstructure"],
                },
                {
                    "context_id": "ctx_off_target_evidence",
                    "label": "Evidence scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "build platform preheating temperature"
                        ]
                    },
                    "property_scope": ["ductility", "microstructure"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    primary = understanding["presentation"]["primary_findings"]
    assert primary
    assert primary[0]["title"] == "heat treatment -> density and microstructure"
    assert all(
        finding["title"] != "build platform preheating temperature -> ductility"
        for finding in understanding["presentation"]["findings"]
    )
    assert all(
        finding["title"] != "scanning speed -> densification, microstructure, and mechanical properties"
        for finding in understanding["presentation"]["findings"]
    )
    assert all(
        finding["title"] != "VED -> fatigue life"
        for finding in understanding["presentation"]["findings"]
    )


def test_objective_understanding_recovers_heat_treatment_density_evidence_without_mechanics_when_not_requested():
    microstructure_text = (
        "Microstructure: A relatively higher density of SLM samples with low "
        "porosity was obtained by increasing the applied laser energy density. "
        "It was confirmed that the heat treatments of the SLM samples induced "
        "an increase in the density. The EBSD and TEM analyses revealed that "
        "the cellular microstructure and dense dislocation structures of the "
        "as-SLM disappeared after the short heat treatments owing to "
        "recrystallization."
    )
    mechanics_text = (
        "Mechanical properties: For the HIP-SLM(120/100), the tensile strength "
        "and elongation were found to be 573.9 MPa and 52.2%, respectively. "
        "The decrease in the hardness and tensile strength and the increase in "
        "the elongation after the heat treatments were attributed to the "
        "reduction in the dislocation density and cellular microstructures."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FailingSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-heat",
                    human_readable_id=4,
                    title="Heat treatment effect on SLM 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-heat-microstructure",
                    document_id="paper-heat",
                    block_type="list_item",
                    text=microstructure_text,
                    block_order=133,
                    page=12,
                    heading_path="4. Conclusion",
                ),
                SourceBlock(
                    block_id="blk-heat-mechanics",
                    document_id="paper-heat",
                    block_type="list_item",
                    text=mechanics_text,
                    block_order=134,
                    page=12,
                    heading_path="4. Conclusion",
                ),
            ],
        ),
    )
    payload = {
        "collection_id": "col-heat",
        "objective": {
            "objective_id": "obj-heat",
            "question": (
                "How do heat treatment type and heat treatment parameters "
                "affect density and microstructure of stainless steel 316L?"
            ),
            "material_scope": ["stainless steel 316L"],
            "process_axes": ["heat treatment"],
            "property_axes": ["density", "microstructure"],
        },
        "objective_context": {
            "objective_id": "obj-heat",
            "question": (
                "How do heat treatment type and heat treatment parameters "
                "affect density and microstructure of stainless steel 316L?"
            ),
            "material_scope": ["stainless steel 316L"],
            "variable_process_axes": ["heat treatment"],
            "target_property_axes": ["density", "microstructure"],
        },
        "paper_frames": [{"document_id": "paper-heat", "relevance": "high"}],
        "evidence_units": [],
        "logic_chain": {"evidence_unit_ids": [], "summary": ""},
    }

    understanding = service.build_objective_understanding(payload)

    finding = understanding["presentation"]["primary_findings"][0]
    assert finding["title"] == "heat treatment -> density and microstructure"
    assert finding["mediators"] == [
        "cellular microstructure",
        "dislocation structures",
        "recrystallization",
    ]
    assert finding["support_grade"] == "partial"
    assert finding["review_status"] == "needs_review"
    assert finding["statement"] == (
        "Heat treatments increased density. Short heat treatments also "
        "eliminated the as-SLM cellular microstructure and dense dislocation "
        "structures through recrystallization."
    )
    assert "HIP" not in finding["statement"]
    assert "porosity" not in finding["statement"]
    assert "removed porosity, cellular microstructure" not in finding["statement"]
    assert finding["evidence_bundle"]["direct_result"] == [
        "evref_recovered_heat_treatment_microstructure_mechanics_blk-heat-microstructure",
    ]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    assert "increase in the density" in evidence_by_id[
        "evref_recovered_heat_treatment_microstructure_mechanics_blk-heat-microstructure"
    ]["quote"]
    assert (
        "evref_recovered_heat_treatment_microstructure_mechanics_mechanics_blk-heat-mechanics"
        not in evidence_by_id
    )
    coverage = {
        item["axis"]: item["status"]
        for item in understanding["presentation"]["summary"]["axis_coverage"][
            "properties"
        ]
    }
    assert coverage == {"density": "primary", "microstructure": "primary"}
    assert "densification" not in coverage
    assert "mechanical properties" not in coverage


def test_objective_understanding_recovers_heat_treatment_conditions_without_claiming_isolation():
    condition_text = (
        "Two different types of heat treatments were applied to the SLM "
        "SS316L: a typical furnace-type heat treatment was conducted at "
        "1100 °C for 0.5 h in an Ar-H2 atmosphere, followed by furnace "
        "cooling. Hot isostatic pressing (HIP) was performed at 1100 °C and "
        "100 MPa for 1.5 h in an Ar atmosphere."
    )
    result_text = (
        "Microstructure: It was confirmed that the heat treatments of the "
        "SLM samples induced an increase in the density. The EBSD and TEM "
        "analyses revealed that the cellular microstructure and dense "
        "dislocation structures of the as-SLM disappeared after the short "
        "heat treatments owing to recrystallization."
    )
    comparison_text = (
        "Two different heat treatments (i.e., typical furnace-type HT and "
        "HIP) were applied to the SLM samples. No superiority was found "
        "between the furnace-type HT and HIP in terms of pore reduction."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FailingSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-heat",
                    human_readable_id=4,
                    title="Heat treatment effect on SLM 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-heat-conditions",
                    document_id="paper-heat",
                    block_type="paragraph",
                    text=condition_text,
                    block_order=39,
                    page=2,
                    heading_path="2.1. Sample preparation and experimental setup",
                ),
                SourceBlock(
                    block_id="blk-heat-comparison",
                    document_id="paper-heat",
                    block_type="paragraph",
                    text=comparison_text,
                    block_order=132,
                    page=12,
                    heading_path="4. Conclusion",
                ),
                SourceBlock(
                    block_id="blk-heat-result",
                    document_id="paper-heat",
                    block_type="list_item",
                    text=result_text,
                    block_order=133,
                    page=12,
                    heading_path="4. Conclusion",
                ),
            ],
        ),
    )
    payload = {
        "collection_id": "col-heat",
        "objective": {
            "objective_id": "obj-heat",
            "question": (
                "How do heat treatment type and heat treatment parameters "
                "affect density and microstructure of stainless steel 316L?"
            ),
            "material_scope": ["stainless steel 316L"],
            "process_axes": ["heat treatment type", "heat treatment parameters"],
            "property_axes": ["density", "microstructure"],
        },
        "objective_context": {
            "objective_id": "obj-heat",
            "question": (
                "How do heat treatment type and heat treatment parameters "
                "affect density and microstructure of stainless steel 316L?"
            ),
            "material_scope": ["stainless steel 316L"],
            "variable_process_axes": [
                "heat treatment type",
                "heat treatment parameters",
            ],
            "target_property_axes": ["density", "microstructure"],
        },
        "paper_frames": [{"document_id": "paper-heat", "relevance": "high"}],
        "evidence_units": [],
        "logic_chain": {"evidence_unit_ids": [], "summary": ""},
    }

    understanding = service.build_objective_understanding(payload)

    findings = understanding["presentation"]["primary_findings"]
    assert len(findings) == 2
    finding = next(
        item
        for item in findings
        if item["title"]
        == "heat treatment type and heat treatment parameters -> density and microstructure"
    )
    assert finding["title"] == (
        "heat treatment type and heat treatment parameters -> density and microstructure"
    )
    assert finding["statement"] == (
        "Under the tested furnace HT at 1100 °C for 0.5 h and HIP at "
        "1100 °C and 100 MPa for 1.5 h, heat treatment increased density and "
        "eliminated the as-SLM cellular microstructure and dense dislocation "
        "structures through recrystallization. These grouped observations do "
        "not isolate treatment type, temperature, duration, or pressure as "
        "separate effects."
    )
    assert finding["variables"] == [
        "heat treatment type and heat treatment parameters"
    ]
    assert finding["support_grade"] == "partial"
    assert {
        "heat_treatment_parameters_not_isolated",
        "single_variable_effect_not_isolated",
        "needs_expert_review",
    }.issubset(finding["warnings"])
    condition_ref_id = (
        "evref_recovered_heat_treatment_microstructure_mechanics_condition_"
        "blk-heat-conditions"
    )
    comparison_ref_id = (
        "evref_recovered_heat_treatment_bundle_pore_reduction_"
        "blk-heat-comparison"
    )
    assert finding["evidence_bundle"]["direct_result"] == [
        "evref_recovered_heat_treatment_microstructure_mechanics_blk-heat-result",
    ]
    assert finding["evidence_bundle"]["condition_context"] == [condition_ref_id]
    comparison_finding = next(
        item
        for item in findings
        if item["title"]
        == "heat treatment type and heat treatment parameters -> pore reduction"
    )
    assert comparison_finding["statement"] == (
        "Under the tested furnace HT at 1100 °C for 0.5 h and HIP at "
        "1100 °C and 100 MPa for 1.5 h, the authors reported no superiority "
        "between the furnace HT and HIP treatment bundles for pore reduction. "
        "This bundle comparison does not isolate treatment type, temperature, "
        "duration, or pressure as separate effects."
    )
    assert comparison_finding["evidence_bundle"]["direct_result"] == [
        comparison_ref_id
    ]
    assert comparison_finding["evidence_bundle"]["condition_context"] == [
        "evref_recovered_heat_treatment_bundle_pore_reduction_condition_"
        "blk-heat-conditions"
    ]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    assert evidence_by_id[condition_ref_id]["evidence_role"] == "condition_context"
    assert "1100 °C and 100 MPa for 1.5 h" in evidence_by_id[condition_ref_id][
        "quote"
    ]
    assert "No superiority" in evidence_by_id[comparison_ref_id]["quote"]
    reprojected = service.with_presentation(understanding)
    assert reprojected is not None
    assert {
        item["finding_id"]
        for item in reprojected["presentation"]["primary_findings"]
    } == {finding["finding_id"], comparison_finding["finding_id"]}


def test_objective_understanding_recovers_heat_treatment_mechanics_when_requested():
    microstructure_text = (
        "Microstructure: A relatively higher density of SLM samples with low "
        "porosity was obtained by increasing the applied laser energy density. "
        "It was confirmed that the heat treatments of the SLM samples induced "
        "an increase in the density. The EBSD and TEM analyses revealed that "
        "the cellular microstructure and dense dislocation structures of the "
        "as-SLM disappeared after the short heat treatments owing to "
        "recrystallization."
    )
    mechanics_text = (
        "Mechanical properties: For the HIP-SLM(120/100), the tensile strength "
        "and elongation were found to be 573.9 MPa and 52.2%, respectively. "
        "The decrease in the hardness and tensile strength and the increase in "
        "the elongation after the heat treatments were attributed to the "
        "reduction in the dislocation density and cellular microstructures."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FailingSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-heat",
                    human_readable_id=4,
                    title="Heat treatment effect on SLM 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-heat-microstructure",
                    document_id="paper-heat",
                    block_type="list_item",
                    text=microstructure_text,
                    block_order=133,
                    page=12,
                    heading_path="4. Conclusion",
                ),
                SourceBlock(
                    block_id="blk-heat-mechanics",
                    document_id="paper-heat",
                    block_type="list_item",
                    text=mechanics_text,
                    block_order=134,
                    page=12,
                    heading_path="4. Conclusion",
                ),
            ],
        ),
    )
    payload = {
        "collection_id": "col-heat",
        "objective": {
            "objective_id": "obj-heat",
            "question": (
                "How do heat treatment type and heat treatment parameters "
                "affect microstructure and mechanical properties of stainless steel 316L?"
            ),
            "material_scope": ["stainless steel 316L"],
            "process_axes": ["heat treatment"],
            "property_axes": ["microstructure", "mechanical properties"],
        },
        "objective_context": {
            "objective_id": "obj-heat",
            "question": (
                "How do heat treatment type and heat treatment parameters "
                "affect microstructure and mechanical properties of stainless steel 316L?"
            ),
            "material_scope": ["stainless steel 316L"],
            "variable_process_axes": ["heat treatment"],
            "target_property_axes": ["microstructure", "mechanical properties"],
        },
        "paper_frames": [{"document_id": "paper-heat", "relevance": "high"}],
        "evidence_units": [],
        "logic_chain": {"evidence_unit_ids": [], "summary": ""},
    }

    understanding = service.build_objective_understanding(payload)

    finding = understanding["presentation"]["primary_findings"][0]
    assert finding["title"] == "heat treatment -> microstructure, hardness, tensile strength, and elongation"
    assert (
        "associated with lower hardness, lower tensile strength, and higher elongation"
        in finding["statement"]
    )
    assert finding["evidence_bundle"]["direct_result"] == [
        "evref_recovered_heat_treatment_microstructure_mechanics_blk-heat-microstructure",
        "evref_recovered_heat_treatment_microstructure_mechanics_mechanics_blk-heat-mechanics",
    ]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    assert "increase in the density" in evidence_by_id[
        "evref_recovered_heat_treatment_microstructure_mechanics_blk-heat-microstructure"
    ]["quote"]
    assert "573.9 MPa and 52.2%" in evidence_by_id[
        "evref_recovered_heat_treatment_microstructure_mechanics_mechanics_blk-heat-mechanics"
    ]["quote"]


def test_objective_understanding_promotes_porosity_corrosion_result_to_primary_finding():
    source_text = (
        "Changes in laser power and scanning speed formed different solidified "
        "melt pool morphologies, leading to various porosities development. "
        "The electrochemical polarization curves and EIS results revealed that "
        "porosities were highly sensitive to pitting corrosion. The pitting "
        "potential gradually increases with the decreased porosity. Meanwhile, "
        "higher resistance can slow the corrosion rate in the polarization "
        "reaction. Therefore, the passive film formed on the surface of low "
        "porosity sample was more stable and exhibited better corrosion "
        "properties."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-corrosion",
                    human_readable_id=5,
                    title="Influence of porosity on corrosion properties of SLM 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-corrosion-result",
                    document_id="paper-corrosion",
                    block_type="paragraph",
                    text=source_text,
                    block_order=91,
                    page=8,
                    heading_path="4 Conclusion",
                )
            ],
        ),
    )
    payload = {
        "collection_id": "col-corrosion",
        "objective": {
            "objective_id": "obj-corrosion",
            "question": "How does porosity affect pitting corrosion behavior?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["porosity level", "pore size"],
            "property_axes": ["pitting corrosion behavior"],
        },
        "objective_context": {
            "objective_id": "obj-corrosion",
            "question": "How does porosity affect pitting corrosion behavior?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["porosity level", "pore size"],
            "target_property_axes": ["pitting corrosion behavior"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-porosity-corrosion",
                "document_id": "paper-corrosion",
                "unit_kind": "sample_context",
                "property_normalized": "pitting corrosion behavior",
                "material_system": {"material": "316L stainless steel"},
                "sample_context": {
                    "porosity_level": "higher",
                    "pore_size": "larger",
                },
                "process_context": {"process": "selective laser melting"},
                "test_condition": {
                    "environment": "pitting corrosion",
                    "test": "electrochemical polarization test",
                },
                "value_payload": {
                    "pitting_potential": "increases",
                    "corrosion_rate": "slows",
                },
                "interpretation": (
                    "Higher porosity reduces pitting potential and increases "
                    "corrosion rate."
                ),
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "blk-corrosion-result",
                        "role": "current_experimental_evidence",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        ],
        "logic_chain": {
            "evidence_unit_ids": ["oeu-porosity-corrosion"],
            "summary": "",
        },
    }

    understanding = service.build_objective_understanding(payload)

    assert understanding["claims"][0]["statement"] == (
        "Higher porosity reduces pitting potential and increases corrosion rate."
    )
    assert understanding["relations"][0]["subject"] == "porosity level"
    finding = understanding["presentation"]["primary_findings"][0]
    assert finding["title"] == "porosity level -> pitting corrosion behavior"
    assert finding["statement"] == (
        "Across the tested SLM conditions, lower-porosity samples were associated "
        "with higher pitting potential and a more stable passive film, consistent "
        "with better pitting-corrosion resistance. Laser power and scan speed "
        "changed together across the samples, so the evidence does not isolate "
        "porosity as a causal variable."
    )
    assert finding["direction"] == "associated"
    assert "paper_level_association" in finding["warnings"]
    assert "process_conditions_not_isolated" in finding["review_reasons"]
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert "pitting potential gradually increases" in evidence_item["quote"]
    assert "passive film" in evidence_item["quote"]


def test_objective_understanding_recovers_porosity_corrosion_finding_from_source_text_when_units_are_metric_tables():
    conclusion_text = (
        "Changes in laser power and scanning speed formed different solidified "
        "melt pool morphologies, leading to various porosities development. "
        "The electrochemical polarization curves and EIS results revealed that "
        "porosities were highly sensitive to pitting corrosion. The pitting "
        "potential gradually increases with the decreased porosity. Meanwhile, "
        "higher resistance can slow the corrosion rate in the polarization "
        "reaction. Therefore, the passive film formed on the surface of low "
        "porosity sample was more stable and exhibited better corrosion "
        "properties."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-corrosion",
                    human_readable_id=5,
                    title="Influence of porosity on corrosion properties of SLM 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-corrosion-conclusion",
                    document_id="paper-corrosion",
                    block_type="paragraph",
                    text=conclusion_text,
                    block_order=91,
                    page=8,
                    heading_path="4 Conclusion",
                )
            ],
            tables=[
                SourceTable(
                    table_id="tbl-corrosion-process",
                    document_id="paper-corrosion",
                    table_order=1,
                    page=2,
                    caption_text="Table 1 SLM 316L process parameters",
                    caption_block_id=None,
                    bbox=None,
                    heading_path="2 Experimental",
                    column_headers=[
                        "Test",
                        "Laser power (W)",
                        "Scan speed (mm/s)",
                        "Layer thickness (μm)",
                        "Energy density (J/mm3)",
                    ],
                    table_matrix=[
                        [
                            "Test",
                            "Laser power (W)",
                            "Scan speed (mm/s)",
                            "Layer thickness (μm)",
                            "Energy density (J/mm3)",
                        ],
                        ["1", "375", "2100", "20", "100"],
                        ["2", "255", "1400", "20", "100"],
                        ["3", "135", "750", "20", "100"],
                    ],
                ),
                SourceTable(
                    table_id="tbl-corrosion-polarization",
                    document_id="paper-corrosion",
                    table_order=3,
                    page=7,
                    caption_text=(
                        "Table 3 Electrochemical parameters results obtained "
                        "from the polarization test"
                    ),
                    caption_block_id=None,
                    bbox=None,
                    heading_path="3 Results and discussion > 3.3 Corrosion properties",
                    column_headers=[
                        "Sample",
                        "E corr (mV)",
                        "E p (mV)",
                    ],
                    table_matrix=[
                        ["Sample", "E corr (mV)", "E p (mV)"],
                        ["375 W-2100 mm·s -1", "-312.9", "124.7"],
                        ["255 W-1400 mm·s -1", "-192.0", "199.7"],
                    ],
                )
            ],
        ),
    )
    payload = {
        "collection_id": "col-corrosion",
        "objective": {
            "objective_id": "obj-corrosion",
            "question": "How does porosity affect pitting corrosion behavior?",
            "material_scope": ["316L stainless steel"],
            "process_axes": [
                "laser power",
                "scanning speed",
                "porosity level",
                "pore size",
            ],
            "property_axes": ["pitting corrosion behavior"],
        },
        "objective_context": {
            "objective_id": "obj-corrosion",
            "question": "How does porosity affect pitting corrosion behavior?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": [
                "laser power",
                "scanning speed",
                "porosity level",
                "pore size",
            ],
            "target_property_axes": ["pitting corrosion behavior"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-pitting-table",
                "document_id": "paper-corrosion",
                "unit_kind": "comparison",
                "property_normalized": "pitting potential",
                "process_context": {
                    "laser_power": "255 W",
                    "scan_speed": "1400 mm/s",
                },
                "baseline_context": {
                    "process_context": {
                        "laser_power": "375 W",
                        "scan_speed": "2100 mm/s",
                    },
                    "source_value_text": "124.7",
                    "value": 124.7,
                },
                "value_payload": {
                    "comparison_axis": "laser power, scanning speed",
                    "current_value": 199.7,
                    "direction": "increase",
                    "source_value_text": "199.7",
                    "value": 199.7,
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "tbl-corrosion-polarization",
                        "role": "current_experimental_evidence",
                        "evidence_role": "direct_support",
                        "page": 7,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.62,
            }
        ],
        "logic_chain": {
            "evidence_unit_ids": ["oeu-pitting-table"],
            "summary": "",
        },
    }

    understanding = service.build_objective_understanding(payload)

    primary = understanding["presentation"]["primary_findings"]
    assert primary[0]["title"] == "porosity level -> pitting corrosion behavior"
    assert primary[0]["variables"] == ["porosity level"]
    assert primary[0]["statement"] == (
        "Across the tested SLM conditions, lower-porosity samples were associated "
        "with higher pitting potential and a more stable passive film, consistent "
        "with better pitting-corrosion resistance. Laser power and scan speed "
        "changed together across the samples, so the evidence does not isolate "
        "porosity as a causal variable."
    )
    assert primary[0]["direction"] == "associated"
    assert "paper_level_association" in primary[0]["warnings"]
    assert "process_conditions_not_isolated" in primary[0]["review_reasons"]
    assert primary[0]["evidence_bundle"]["direct_result"] == [
        "evref_recovered_porosity_corrosion_blk-corrosion-conclusion"
    ]
    assert primary[0]["evidence_bundle"]["condition_context"] == [
        "evref_recovered_porosity_corrosion_condition_tbl-corrosion-process"
    ]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    recovered = evidence_by_id["evref_recovered_porosity_corrosion_blk-corrosion-conclusion"]
    assert recovered["source_ref"] == "blk-corrosion-conclusion"
    assert recovered["page"] == "8"
    assert "pitting potential gradually increases" in recovered["quote"]
    assert "passive film" in recovered["quote"]
    condition = evidence_by_id[
        "evref_recovered_porosity_corrosion_condition_tbl-corrosion-process"
    ]
    assert condition["source_ref"] == "tbl-corrosion-process"
    assert condition["source_kind"] == "table"
    assert "Laser power" in condition["quote"]
    assert "Scan speed" in condition["quote"]


def test_objective_understanding_recovers_preheating_ductility_finding_from_conclusion_when_units_are_metric_tables():
    conclusion_text = (
        "Preheating the build platform to 150 °C increased the ductility of "
        "material by 14%. This is attributed to the more homogenized "
        "microstructure as well as cellular structure with geometry necessary "
        "dislocations (GNDs), thereby material accommodated more plastic "
        "strains during deformation."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(
            [
                {
                    "relation_type": "comparison",
                    "source_concept": "build platform preheating temperature",
                    "target_concept": "elongation",
                    "mediator_concepts": [],
                    "direction": "increases",
                    "statement": (
                        "The source table reports elongation of 72% for the "
                        "non-preheated condition and 82% for the preheated condition."
                    ),
                    "conditions": ["316L stainless steel"],
                    "evidence_unit_ids": ["oeu-preheat-elongation"],
                    "confidence": 0.9,
                    "warnings": [],
                }
            ]
        ),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-preheat",
                    human_readable_id=2,
                    title="Effect of Preheating Build Platform on LPBF 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-preheat-conclusion",
                    document_id="paper-preheat",
                    block_type="list_item",
                    text=conclusion_text,
                    block_order=240,
                    page=9,
                    heading_path="Conclusions and future study",
                )
            ],
            tables=[
                SourceTable(
                    table_id="tbl-preheat-tensile",
                    document_id="paper-preheat",
                    table_order=2,
                    page=8,
                    caption_text=(
                        "Table 2. Monotonic tensile properties of 316L SS "
                        "fabricated under argon shielding gas in both "
                        "non-preheated and preheated build platform conditions."
                    ),
                    caption_block_id=None,
                    bbox=None,
                    heading_path="Tensile properties",
                    column_headers=[
                        "Build platform conditions",
                        "ı y (MPa)",
                        "ı u (MPa)",
                        "El%",
                    ],
                    table_matrix=[
                        ["Build platform conditions", "ı y (MPa)", "ı u (MPa)", "El%"],
                        ["Non-preheated", "448", "617", "72"],
                        ["Preheated", "465", "618", "82"],
                    ],
                )
            ],
        ),
    )
    payload = {
        "collection_id": "col-preheat",
        "objective": {
            "objective_id": "obj-preheat",
            "question": (
                "How does build platform preheating affect microstructure and "
                "mechanical properties of 316L stainless steel?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": [
                "build platform preheating temperature",
                "build platform preheating",
            ],
            "property_axes": ["microstructure", "mechanical properties"],
        },
        "objective_context": {
            "objective_id": "obj-preheat",
            "question": (
                "How does build platform preheating affect microstructure and "
                "mechanical properties of 316L stainless steel?"
            ),
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": [
                "build platform preheating temperature",
                "build platform preheating",
            ],
            "target_property_axes": ["microstructure", "mechanical properties"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-preheat-elongation",
                "document_id": "paper-preheat",
                "unit_kind": "comparison",
                "property_normalized": "elongation",
                "process_context": {
                    "Build platform conditions": "Preheated",
                    "build_platform_preheating_temperature": "150 °C",
                },
                "baseline_context": {
                    "Build platform conditions": "Non-preheated",
                    "source_value_text": "72",
                    "value": 72,
                },
                "value_payload": {
                    "comparison_axis": "build platform preheating temperature",
                    "current_value": 82,
                    "direction": "increase",
                    "source_value_text": "82",
                    "value": 82,
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "tbl-preheat-tensile",
                        "role": "current_experimental_evidence",
                        "evidence_role": "direct_support",
                        "page": 8,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        ],
        "logic_chain": {
            "evidence_unit_ids": ["oeu-preheat-elongation"],
            "summary": "",
        },
    }

    understanding = service.build_objective_understanding(payload)

    primary = understanding["presentation"]["primary_findings"]
    assert primary[0]["title"] == "build platform preheating temperature -> elongation"
    assert primary[0]["variables"] == ["build platform preheating temperature"]
    assert primary[0]["mediators"] == [
        "microstructure",
        "GNDs",
        "cellular microstructure",
    ]
    assert primary[0]["statement"] == (
        "The source table reports elongation of 72% for the non-preheated "
        "condition and 82% for the preheated condition. Preheating the build "
        "platform to 150 °C increased ductility by 14%; the authors attributed "
        "this increase to a more homogenized cellular microstructure and "
        "GND-assisted plastic deformation."
    )
    assert "author_attributed_mechanism" in primary[0]["warnings"]
    assert "author_attributed_mechanism" in primary[0]["review_reasons"]
    direct_result_refs = primary[0]["evidence_bundle"]["direct_result"]
    assert direct_result_refs[0] == (
        "evref_recovered_preheating_ductility_blk-preheat-conclusion"
    )
    assert len(direct_result_refs) == 2
    assert primary[0]["evidence_bundle"]["mechanism"] == [
        "evref_recovered_preheating_ductility_blk-preheat-conclusion"
    ]
    assert primary[0]["comparison_summary"] == {
        "variable": "build platform preheating temperature",
        "direction": "increases",
        "outcome": "elongation",
        "baseline": {"label": "non-preheated", "value": "72%"},
        "observed": {"label": "preheated", "value": "82%"},
        "controlled_conditions": [],
    }
    assert all(
        finding["title"] != "build platform preheating temperature -> elongation"
        for finding in understanding["presentation"]["review_queue_findings"]
    )
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    recovered = evidence_by_id["evref_recovered_preheating_ductility_blk-preheat-conclusion"]
    assert recovered["source_ref"] == "blk-preheat-conclusion"
    assert recovered["page"] == "9"
    assert "150 °C increased the ductility" in recovered["quote"]
    assert "GNDs" in recovered["quote"]
    assert "quote=" in (recovered["href"] or "")
    assert "150%20%C2%B0C%20increased" in (recovered["href"] or "")
    table_ref = evidence_by_id[direct_result_refs[1]]
    assert table_ref["source_ref"] == "tbl-preheat-tensile"
    assert table_ref["page"] == "8"
    assert "Non-preheated" in table_ref["quote"]
    assert "Preheated" in table_ref["quote"]
    assert "72" in table_ref["quote"]
    assert "82" in table_ref["quote"]
    misaligned_narrative = {
        **primary[0],
        "claim_id": "claim-unrelated-to-preheating-recovery",
        "statement": "The treatment increased ductility by 30%.",
        "outcomes": ["ductility"],
        "evidence_bundle": {
            **primary[0]["evidence_bundle"],
            "direct_result": [recovered["evidence_ref_id"]],
        },
    }
    table_candidate = {
        **primary[0],
        "claim_id": "claim-generic-table-comparison",
        "statement": (
            "The source table reports elongation of 72% for the non-preheated "
            "condition and 82% for the preheated condition."
        ),
        "outcomes": ["elongation"],
        "evidence_bundle": {
            **primary[0]["evidence_bundle"],
            "direct_result": [table_ref["evidence_ref_id"]],
        },
    }
    assert not service._table_finding_matches_narrative_finding(
        table_candidate,
        narrative_finding=misaligned_narrative,
        evidence_by_id=evidence_by_id,
    )


def test_finding_promotes_matching_preheat_strength_table():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    table = SourceTable(
        table_id="tbl-preheat-tensile",
        document_id="paper-preheat",
        table_order=2,
        page=8,
        caption_text="Monotonic tensile properties",
        caption_block_id=None,
        bbox=None,
        heading_path="Tensile properties",
        column_headers=(
            "Build platform conditions",
            "ı y (MPa)",
            "ı u (MPa)",
            "El%",
        ),
        table_matrix=(
            ("Non-preheated", "448", "617", "72"),
            ("Preheated", "465", "618", "82"),
        ),
    )

    bundle = service._finding_direct_bundle(
        {
            "direct_result": ["evref-text"],
            "mechanism": ["evref-text"],
            "condition_context": [],
            "background": [],
            "conflict": [],
            "noise": [],
            "uncategorized": ["evref-table"],
        },
        evidence_by_id={
            "evref-text": {"source_kind": "text_window"},
            "evref-table": {
                "source_kind": "table",
                "locator": {"source_ref": "tbl-preheat-tensile"},
                "traceability_status": "resolved",
            },
        },
        outcomes=["mechanical properties"],
        promote_non_table=False,
        statement="Preheating increased yield strength by approximately 4%.",
        tables_by_id={"tbl-preheat-tensile": table},
    )

    assert bundle["direct_result"] == ["evref-text", "evref-table"]
    assert bundle["uncategorized"] == []


def test_objective_understanding_does_not_recover_mechanical_finding_for_corrosion_goal():
    slm_mechanical_conclusion = (
        "The SLM samples processed at higher scanning speed exhibited better "
        "densification, refined microstructure, and excellent mechanical "
        "properties as compared to samples processed with lower scanning speed."
    )
    corrosion_conclusion = (
        "The electrochemical polarization curves and EIS results revealed that "
        "porosities were highly sensitive to pitting corrosion. The pitting "
        "potential gradually increases with the decreased porosity. Meanwhile, "
        "higher resistance can slow the corrosion rate in the polarization "
        "reaction. Therefore, the passive film formed on the surface of low "
        "porosity sample was more stable and exhibited better corrosion "
        "properties."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-slm",
                    human_readable_id=1,
                    title="SLM processing and mechanical properties",
                    text="",
                ),
                SourceDocument(
                    document_id="paper-corrosion",
                    human_readable_id=5,
                    title="Influence of porosity on corrosion properties of SLM 316L",
                    text="",
                ),
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-slm-mechanical-conclusion",
                    document_id="paper-slm",
                    block_type="list_item",
                    text=slm_mechanical_conclusion,
                    block_order=115,
                    page=12,
                    heading_path="4. Conclusion",
                ),
                SourceBlock(
                    block_id="blk-corrosion-conclusion",
                    document_id="paper-corrosion",
                    block_type="paragraph",
                    text=corrosion_conclusion,
                    block_order=91,
                    page=8,
                    heading_path="4 Conclusion",
                ),
            ],
        ),
    )
    payload = {
        "collection_id": "col-corrosion",
        "objective": {
            "objective_id": "obj-corrosion",
            "question": (
                "How do laser power, scanning speed, energy density, porosity "
                "level, and pore size affect pitting corrosion behavior?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": [
                "laser power",
                "scanning speed",
                "energy density",
                "porosity level",
                "pore size",
            ],
            "property_axes": ["pitting corrosion behavior"],
        },
        "objective_context": {
            "objective_id": "obj-corrosion",
            "question": (
                "How do laser power, scanning speed, energy density, porosity "
                "level, and pore size affect pitting corrosion behavior?"
            ),
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": [
                "laser power",
                "scanning speed",
                "energy density",
                "porosity level",
                "pore size",
            ],
            "target_property_axes": ["pitting corrosion behavior"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-slm-background",
                "document_id": "paper-slm",
                "unit_kind": "comparison",
                "property_normalized": "relative density",
                "process_context": {"energy_density": "70 J/mm3"},
                "value_payload": {
                    "comparison_axis": "energy density",
                    "summary": "energy density affected density",
                },
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "blk-slm-mechanical-conclusion",
                        "role": "background_context",
                    }
                ],
            },
            {
                "evidence_unit_id": "oeu-porosity-corrosion",
                "document_id": "paper-corrosion",
                "unit_kind": "comparison",
                "property_normalized": "pitting corrosion behavior",
                "process_context": {"porosity_level": "low"},
                "value_payload": {
                    "comparison_axis": "porosity level",
                    "summary": "porosity affects pitting corrosion",
                },
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "blk-corrosion-conclusion",
                        "role": "current_experimental_evidence",
                    }
                ],
                "resolution_status": "resolved",
            },
        ],
        "logic_chain": {"evidence_unit_ids": ["oeu-porosity-corrosion"]},
    }

    understanding = service.build_objective_understanding(payload)

    primary = understanding["presentation"]["primary_findings"]
    assert [finding["title"] for finding in primary] == [
        "porosity level -> pitting corrosion behavior"
    ]
    all_titles = [finding["title"] for finding in understanding["presentation"]["findings"]]
    assert "scanning speed -> densification, microstructure, and mechanical properties" not in all_titles


def test_objective_understanding_prefers_heat_treatment_result_block_over_abstract():
    abstract_text = (
        "The heat treatments of the fabricated SLM samples induced the removal "
        "of porosity, cellular microstructure, and dense dislocation structures. "
        "The heat treatments improved elongation, while surface hardness and "
        "tensile strength decreased owing to microstructural evolution."
    )
    result_text = (
        "Mechanical properties: The SLM samples exhibited a relatively lower "
        "surface hardness than the conventional CR. Notwithstanding the higher "
        "density, the HT-SLM and HIP-SLM showed a relatively lower surface "
        "hardness than that of the as-SLM. From the tensile test, the as-SLM "
        "fabricated at 120 W and 100 mm/s exhibited a similar tensile strength, "
        "as well as a significantly lower elongation compared with those of the "
        "CR. The average tensile strength and elongation values were 593.0 MPa "
        "and 35.0% for the as-SLM(120/100). The heat treatments induced a "
        "decrease in the tensile strength, as well as an increase in the "
        "elongation. For the HIP-SLM(120/100), the tensile strength and "
        "elongation were found to be 573.9 MPa and 52.2%, respectively. The "
        "decrease in hardness and tensile strength and the increase in "
        "elongation after the heat treatments were attributed to the reduction "
        "in the dislocation density and cellular microstructures."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-heat",
                    human_readable_id=4,
                    title="Heat treatment effect on SLM 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-heat-abstract",
                    document_id="paper-heat",
                    block_type="paragraph",
                    text=abstract_text,
                    block_order=23,
                    page=1,
                    heading_path="A B S T R A C T",
                ),
                SourceBlock(
                    block_id="blk-heat-conclusion",
                    document_id="paper-heat",
                    block_type="list_item",
                    text=result_text,
                    block_order=134,
                    page=12,
                    heading_path="4. Conclusion",
                ),
            ],
        ),
    )
    payload = {
        "collection_id": "col-heat",
        "objective": {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect density and microstructure?",
            "material_scope": ["stainless steel 316L"],
            "process_axes": ["heat treatment", "heat treatment type"],
            "property_axes": ["density", "microstructure"],
        },
        "objective_context": {
            "objective_id": "obj-heat",
            "question": "How does heat treatment affect density and microstructure?",
            "material_scope": ["stainless steel 316L"],
            "variable_process_axes": ["heat treatment", "heat treatment type"],
            "target_property_axes": ["density", "microstructure"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-heat",
                "document_id": "paper-heat",
                "unit_kind": "comparison",
                "property_normalized": "density",
                "process_context": {"heat_treatment": "HIP"},
                "value_payload": {
                    "comparison_axis": "heat treatment type",
                    "summary": "heat treatment changed density and microstructure",
                },
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "blk-heat-conclusion",
                        "role": "current_experimental_evidence",
                    }
                ],
                "resolution_status": "resolved",
            }
        ],
        "logic_chain": {"evidence_unit_ids": ["oeu-heat"]},
    }

    understanding = service.build_objective_understanding(payload)

    primary = understanding["presentation"]["primary_findings"]
    assert primary[0]["title"] == "heat treatment -> density and microstructure"
    assert primary[0]["outcomes"] == ["density", "microstructure"]
    assert (
        "associated with lower hardness and tensile strength and higher elongation"
        not in primary[0]["statement"]
    )
    assert "True" not in primary[0]["scope_summary"]
    assert primary[0]["evidence_bundle"]["direct_result"] == [
        "evref_recovered_heat_treatment_microstructure_mechanics_blk-heat-conclusion"
    ]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    recovered = evidence_by_id[
        "evref_recovered_heat_treatment_microstructure_mechanics_blk-heat-conclusion"
    ]
    assert recovered["source_ref"] == "blk-heat-conclusion"
    assert recovered["page"] == "12"
    assert "density" in recovered["quote"]


def test_objective_understanding_recovers_ved_fatigue_from_relevant_frames_when_units_empty():
    fatigue_text = (
        "The present results indicate that the increasing VED leads to lower "
        "fraction of defects, slightly smaller defect size and complexity, and "
        "improves slightly the fatigue life, but still the fatigue resistance "
        "remains distinctly lower than that of the wrought 316L steel."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-fatigue",
                    human_readable_id=3,
                    title="VED, defects and fatigue in PBF-LB 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-fatigue-result",
                    document_id="paper-fatigue",
                    block_type="paragraph",
                    text=fatigue_text,
                    block_order=139,
                    page=10,
                    heading_path="4.2. The influence of defect structure on fatigue strength",
                )
            ],
            tables=[
                SourceTable(
                    table_id="tbl-fatigue-strength",
                    document_id="paper-fatigue",
                    table_order=5,
                    caption_text=(
                        "Table 5 Ratios of fatigue limit to Tensile Strength "
                        "(TS), Fatigue Limit at 50 % probability (FAT50 %), "
                        "Fatigue Limit at 50 % to Ultimate Tensile Strength "
                        "ratio (FAT/UTS), and Fatigue Strength at 10 4 cycles "
                        "(FAT at 10 4 ) for 316L structures printed at different "
                        "VEDs and wrought 316L."
                    ),
                    caption_block_id=None,
                    page=10,
                    bbox=None,
                    heading_path=(
                        "4.2. The influence of defect structure on fatigue strength"
                    ),
                    column_headers=(
                        "Printed 316L",
                        "UTS [MPa]",
                        "FAT50 % [MPa]",
                        "FAT/ UTS -",
                        "FAT at 10 4 cycles [MPa]",
                        "Max. Defect length (LCSM) [ μ m]",
                    ),
                    table_matrix=(
                        (
                            "Printed 316L",
                            "UTS [MPa]",
                            "FAT50 % [MPa]",
                            "FAT/ UTS -",
                            "FAT at 10 4 cycles [MPa]",
                            "Max. Defect length (LCSM) [ μ m]",
                        ),
                        ("L-VED", "610 ± 6", "93", "0.15", "340", "394"),
                        ("M-VED", "595 ± 13", "82", "0.14", "450", "179"),
                        ("H-VED", "560 ± 4", "97", "0.17", "470", "86"),
                        ("Wrought", "624 ± 2", "256", "0.41", "390", "-"),
                    ),
                )
            ],
        ),
    )
    payload = {
        "collection_id": "col-fatigue",
        "objective": {
            "objective_id": "obj-fatigue",
            "question": "How does VED affect defect structure and fatigue strength?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["volumetric energy density", "laser power"],
            "property_axes": ["defect structure", "fatigue strength"],
        },
        "objective_context": {
            "objective_id": "obj-fatigue",
            "question": "How does VED affect defect structure and fatigue strength?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["volumetric energy density", "laser power"],
            "target_property_axes": ["defect structure", "fatigue strength"],
        },
        "paper_frames": [
            {
                "document_id": "paper-fatigue",
                "relevance": "high",
                "measured_property_scope": ["defect structure", "fatigue strength"],
            }
        ],
        "evidence_routes": [
            {
                "document_id": "paper-fatigue",
                "source_kind": "text_window",
                "source_ref": "blk-fatigue-result",
                "role": "current_experimental_evidence",
                "extractable": True,
            }
        ],
        "evidence_units": [],
        "logic_chain": {"evidence_unit_ids": []},
    }

    understanding = service.build_objective_understanding(payload)

    primary = understanding["presentation"]["primary_findings"]
    assert primary[0]["title"] == "VED -> fatigue strength"
    assert primary[0]["outcomes"] == ["fatigue strength"]
    assert primary[0]["mediators"] == ["defect structure"]
    assert "340, 450, and 470 MPa" in primary[0]["statement"]
    assert "394, 179, and 86 μm" in primary[0]["statement"]
    assert "FAT50 was non-monotonic" in primary[0]["statement"]
    assert "93, 82, and 97 MPa" in primary[0]["statement"]
    assert "wrought 316L (256 MPa)" in primary[0]["statement"]
    assert "The authors associated" in primary[0]["statement"]
    assert primary[0]["evidence_bundle"]["direct_result"] == [
        "evref_recovered_ved_defects_fatigue_blk-fatigue-result",
        "evref_recovered_ved_defects_fatigue_table_tbl-fatigue-strength",
    ]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    recovered = evidence_by_id["evref_recovered_ved_defects_fatigue_blk-fatigue-result"]
    assert "lower fraction of defects" in recovered["quote"]
    recovered_table = evidence_by_id[
        "evref_recovered_ved_defects_fatigue_table_tbl-fatigue-strength"
    ]
    assert recovered_table["source_ref"] == "tbl-fatigue-strength"
    assert "340" in recovered_table["quote"]
    assert "450" in recovered_table["quote"]
    assert recovered_table["table_audit"]["columns"] == [
        "Printed 316L",
        "UTS [MPa]",
        "FAT50 % [MPa]",
        "FAT/ UTS -",
        "FAT at 10 4 cycles [MPa]",
        "Max. Defect length (LCSM) [ μ m]",
    ]
    relevant_rows = recovered_table["table_audit"]["relevant_rows"]
    assert all(row["aligned"] for row in relevant_rows)
    assert {row["row_index"]: row["cells"] for row in relevant_rows} == {
        1: ["L-VED", "610 ± 6", "93", "0.15", "340", "394"],
        2: ["M-VED", "595 ± 13", "82", "0.14", "450", "179"],
        3: ["H-VED", "560 ± 4", "97", "0.17", "470", "86"],
        4: ["Wrought", "624 ± 2", "256", "0.41", "390", "-"],
    }
    assert "quote=" in (recovered["href"] or "")
    assert "lower%20fraction%20of%20defects" in (recovered["href"] or "")


def test_with_presentation_refreshes_persisted_ved_fatigue_strength_table_summary():
    fatigue_text = (
        "As pointed out, the defects in PBF-LB materials results in low "
        "fatigue resistance compared to their static properties. "
        "The present results indicate that the increasing VED leads to lower "
        "fraction of defects, slightly smaller defect size and complexity, and "
        "improves slightly the fatigue life, but still the fatigue resistance "
        "remains distinctly lower than that of the wrought 316L steel."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-fatigue",
                    human_readable_id=3,
                    title="VED, defects and fatigue in PBF-LB 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-fatigue-result",
                    document_id="paper-fatigue",
                    block_type="paragraph",
                    text=fatigue_text,
                    block_order=139,
                    page=10,
                    heading_path="4.2. The influence of defect structure on fatigue strength",
                ),
                SourceBlock(
                    block_id="blk-fatigue-condition",
                    document_id="paper-fatigue",
                    block_type="paragraph",
                    text=(
                        "Three sets of samples were deposited using an SLM 280HL "
                        "PBF-LB equipment. By varying the scanning speed and laser "
                        "power, low (L-VED at 50.8 J/mm3), medium (M-VED at 79.4 "
                        "J/mm3), and high (H-VED at 84.3 J/mm3) levels were applied."
                    ),
                    block_order=47,
                    page=3,
                    heading_path="2. Materials and methods",
                ),
            ],
            tables=[
                SourceTable(
                    table_id="tbl-fatigue-strength",
                    document_id="paper-fatigue",
                    table_order=5,
                    caption_text=(
                        "Table 5 Ratios of fatigue limit to Tensile Strength "
                        "(TS), Fatigue Limit at 50 % probability (FAT50 %), "
                        "Fatigue Limit at 50 % to Ultimate Tensile Strength "
                        "ratio (FAT/UTS), and Fatigue Strength at 10 4 cycles "
                        "(FAT at 10 4 ) for 316L structures printed at different "
                        "VEDs and wrought 316L."
                    ),
                    caption_block_id=None,
                    page=10,
                    bbox=None,
                    heading_path=(
                        "4.2. The influence of defect structure on fatigue strength"
                    ),
                    column_headers=(
                        "Printed 316L",
                        "UTS [MPa]",
                        "FAT50 % [MPa]",
                        "FAT/ UTS -",
                        "FAT at 10 4 cycles [MPa]",
                        "Max. Defect length (LCSM) [ μ m]",
                    ),
                    table_matrix=(
                        ("L-VED", "610 ± 6", "93", "0.15", "340", "394"),
                        ("M-VED", "595 ± 13", "82", "0.14", "450", "179"),
                        ("H-VED", "560 ± 4", "97", "0.17", "470", "86"),
                        ("Wrought", "624 ± 2", "256", "0.41", "390", "-"),
                    ),
                )
            ],
        ),
    )
    old_statement = (
        "Increasing VED lowered defect fraction, size, and complexity, which "
        "improved fatigue life; remaining LoF defects still kept fatigue "
        "resistance below wrought 316L steel."
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-fatigue",
                "goal_id": "goal-fatigue",
                "title": (
                    "How do volumetric energy density, laser power, scanning speed, "
                    "hatch spacing, and layer thickness affect defect structure "
                    "and fatigue strength?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_recovered_ved_defects_fatigue_blk-fatigue-result",
                    "claim_type": "finding",
                    "statement": old_statement,
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": [
                        "evref_recovered_ved_defects_fatigue_blk-fatigue-result"
                    ],
                    "context_ids": [
                        "ctx_recovered_ved_defects_fatigue_blk-fatigue-result"
                    ],
                    "source_object_ids": ["blk-fatigue-result"],
                    "warnings": ["needs_expert_review"],
                },
                {
                    "claim_id": "claim_fatigue_strength_table_row",
                    "claim_type": "finding",
                    "statement": (
                        "Under layer thickness 30, volumetric energy density "
                        "increased fatigue strength from 340 MPa (L-VED) to "
                        "450.0 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_fatigue_strength_table_row"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu-fatigue-strength"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_recovered_ved_defects_fatigue_blk-fatigue-result",
                    "relation_type": "compares",
                    "subject": "volumetric energy density",
                    "predicate": "compares",
                    "object": "defect structure -> fatigue life",
                    "statement": old_statement,
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": [
                        "evref_recovered_ved_defects_fatigue_blk-fatigue-result"
                    ],
                    "context_ids": [
                        "ctx_recovered_ved_defects_fatigue_blk-fatigue-result"
                    ],
                    "source_object_ids": ["blk-fatigue-result"],
                    "warnings": ["recovered_from_source_text", "needs_expert_review"],
                },
                {
                    "relation_id": "rel_fatigue_strength_table_row",
                    "relation_type": "increases",
                    "subject": "volumetric energy density",
                    "predicate": "increases",
                    "object": "fatigue strength",
                    "statement": (
                        "Under layer thickness 30, volumetric energy density "
                        "increased fatigue strength from 340 MPa (L-VED) to "
                        "450.0 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_fatigue_strength_table_row"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu-fatigue-strength"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": (
                        "evref_recovered_ved_defects_fatigue_blk-fatigue-result"
                    ),
                    "source_kind": "paragraph",
                    "document_id": "paper-fatigue",
                    "label": "4.2. The influence of defect structure on fatigue strength",
                    "locator": {
                        "source_ref": "blk-fatigue-result",
                        "source_kind": "paragraph",
                        "page": 10,
                    },
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": fatigue_text,
                },
                {
                    "evidence_ref_id": "evref_fatigue_strength_table_row",
                    "source_kind": "table",
                    "document_id": "paper-fatigue",
                    "label": "Table 5",
                    "locator": {
                        "source_ref": "tbl-fatigue-strength",
                        "source_kind": "table",
                        "page": 10,
                    },
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "L-VED | 340 | 394 / M-VED | 450 | 179",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "volumetric energy density",
                            "laser power",
                            "scanning speed",
                            "hatch spacing",
                            "layer thickness",
                        ]
                    },
                    "property_scope": ["defect structure", "fatigue strength"],
                },
                {
                    "context_id": "ctx_recovered_ved_defects_fatigue_blk-fatigue-result",
                    "label": "Recovered source scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["volumetric energy density"]
                    },
                    "property_scope": ["defect structure", "fatigue life"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    primary = understanding["presentation"]["primary_findings"]
    review_queue = understanding["presentation"]["review_queue_findings"]
    finding = primary[0]
    assert finding["title"] == (
        "coupled PBF-LB parameter sets grouped by volumetric energy density -> "
        "fatigue strength"
    )
    assert finding["variables"] == [
        "coupled PBF-LB parameter sets grouped by volumetric energy density"
    ]
    assert finding["outcomes"] == ["fatigue strength"]
    assert "340, 450, and 470 MPa" in finding["statement"]
    assert "394, 179, and 86 μm" in finding["statement"]
    assert "FAT50 was non-monotonic" in finding["statement"]
    assert "wrought 316L (256 MPa)" in finding["statement"]
    assert "does not isolate a VED-only effect" in finding["statement"]
    assert "process_conditions_not_isolated" in finding["warnings"]
    assert "single_variable_effect_not_isolated" in finding["review_reasons"]
    assert finding["evidence_bundle"]["direct_result"] == [
        "evref_recovered_ved_defects_fatigue_blk-fatigue-result",
        "evref_recovered_ved_defects_fatigue_table_tbl-fatigue-strength",
    ]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    visible_quote = evidence_by_id[
        "evref_recovered_ved_defects_fatigue_blk-fatigue-result"
    ]["quote"]
    assert "increasing VED leads to lower fraction of defects" in visible_quote
    assert not visible_quote.startswith("As pointed out")
    assert all(
        item["title"] != "volumetric energy density -> fatigue strength"
        for item in review_queue
    )


def test_objective_understanding_promotes_experimental_texture_yield_validation_trend():
    setup_text = (
        "With a methodology established for predicting the crystallographic "
        "texture of L-PBF manufactured samples based on build orientation and "
        "scan strategy rotation angles, this approach was leveraged for "
        "predicting the yield strength of the materials. The Bishop-Hill models "
        "were adopted, with the established crystallographic texture serving "
        "as the primary input."
    )
    validation_text = (
        "Remarkably, there is a strong alignment between the model's "
        "predictions and experimental findings, with deviations generally less "
        "than 5%. Furthermore, the yield strength increased from the 0-0-0 "
        "configuration to the 45-22.5-0 condition. Additionally, validation "
        "results strongly suggest that improved yield strengths can be achieved "
        "simply by adjusting the scan strategy angle, even without altering the "
        "build orientation."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-texture",
                    human_readable_id=6,
                    title="Scan strategy and build orientation in LPBF 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-angle-definitions",
                    document_id="paper-texture",
                    block_type="paragraph",
                    text=(
                        "The process involved three angles: θ, the rotation "
                        "angle of the laser scan lines; α, rotation about the "
                        "global X-axis; and β, rotation about the global Y-axis."
                    ),
                    block_order=35,
                    page=2,
                    heading_path="2.1. Experiment",
                ),
                SourceBlock(
                    block_id="blk-yield-setup",
                    document_id="paper-texture",
                    block_type="paragraph",
                    text=setup_text,
                    block_order=87,
                    page=8,
                    heading_path="3.4. Yield strength prediction and validation",
                ),
                SourceBlock(
                    block_id="blk-yield-validation",
                    document_id="paper-texture",
                    block_type="paragraph",
                    text=validation_text,
                    block_order=89,
                    page=8,
                    heading_path="3.4. Yield strength prediction and validation",
                ),
            ],
            tables=[
                SourceTable(
                    table_id="tbl-yield-validation",
                    document_id="paper-texture",
                    table_order=3,
                    caption_text=(
                        "Table 3 The prediction and average experimental yield "
                        "strength results of samples built in different scanning "
                        "strategies and building orientations."
                    ),
                    caption_block_id=None,
                    page=8,
                    bbox=None,
                    heading_path="3.4. Yield strength prediction and validation",
                    column_headers=(
                        "α (°)",
                        "β (°)",
                        "θ (°)",
                        "Yield Strength Prediction (MPa)",
                        "Yield Strength Experiment (MPa)",
                    ),
                    table_matrix=(
                        (
                            "α (°)",
                            "β (°)",
                            "θ (°)",
                            "Yield Strength Prediction (MPa)",
                            "Yield Strength Experiment (MPa)",
                        ),
                        ("0", "0", "0", "310.48", "334.2"),
                        ("0", "0", "30", "322.84", "342.5"),
                        ("0", "0", "45", "328.67", "351.9"),
                        ("0", "22.5", "0", "314.37", "295.1"),
                        ("45", "22.5", "0", "341.85", "363.1"),
                        ("45", "22.5", "30", "345.64", "356.9"),
                        ("45", "22.5", "45", "347.14", "365.6"),
                    ),
                )
            ],
        ),
    )
    payload = {
        "collection_id": "col-texture",
        "objective": {
            "objective_id": "obj-texture",
            "question": (
                "How do scan strategy rotation angle and build orientation "
                "affect crystallographic texture and yield strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": ["scan strategy rotation angle", "build orientation"],
            "property_axes": ["crystallographic texture", "yield strength"],
        },
        "objective_context": {
            "objective_id": "obj-texture",
            "question": (
                "How do scan strategy rotation angle and build orientation "
                "affect crystallographic texture and yield strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": [
                "scan strategy rotation angle",
                "build orientation",
            ],
            "target_property_axes": ["crystallographic texture", "yield strength"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-yield",
                "document_id": "paper-texture",
                "unit_kind": "measurement",
                "property_normalized": "yield strength",
                "value_payload": {"source_value_text": "342.5 MPa"},
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": "blk-yield-validation",
                        "role": "current_experimental_evidence",
                    }
                ],
                "resolution_status": "resolved",
            }
        ],
        "logic_chain": {"evidence_unit_ids": ["oeu-yield"]},
    }

    understanding = service.build_objective_understanding(payload)

    primary = understanding["presentation"]["primary_findings"]
    review_queue = understanding["presentation"]["review_queue_findings"]
    assert len(primary) == 2
    build_orientation = _presentation_finding_by_title(
        understanding,
        "α and β build orientation angles -> yield strength",
    )
    scan_rotation = _presentation_finding_by_title(
        understanding,
        "scan strategy rotation angle -> yield strength",
    )
    assert "fixed scan strategy rotation angle θ=0°" in build_orientation[
        "statement"
    ]
    assert "334.2 MPa to 363.1 MPa" in build_orientation["statement"]
    assert "do not uniformly satisfy" in build_orientation["statement"]
    assert "fixed build orientation α=0° and β=0°" in scan_rotation["statement"]
    assert "334.2 MPa to 351.9 MPa" in scan_rotation["statement"]
    assert build_orientation["review_status"] == "needs_review"
    assert build_orientation["expert_use_status"] == "paper_level_finding"
    assert build_orientation["generalization_status"] == "paper_level_only"
    assert build_orientation["comparison_summary"] == {
        "variable": "α and β build orientation angles",
        "direction": "increases",
        "outcome": "yield strength",
        "baseline": {"label": "α=0°, β=0°", "value": "334.2 MPa"},
        "observed": {"label": "α=45°, β=22.5°", "value": "363.1 MPa"},
        "controlled_conditions": [
            {"axis": "scan strategy rotation angle (θ)", "value": "0°"}
        ],
    }
    assert scan_rotation["comparison_summary"] == {
        "variable": "scan strategy rotation angle (θ)",
        "direction": "increases",
        "outcome": "yield strength",
        "baseline": {"label": "θ=0°", "value": "334.2 MPa"},
        "observed": {"label": "θ=45°", "value": "351.9 MPa"},
        "controlled_conditions": [
            {"axis": "α build orientation angle", "value": "0°"},
            {"axis": "β build orientation angle", "value": "0°"},
        ],
    }
    assert "model_validation_finding" in build_orientation["warnings"]
    assert "author_summary_table_mismatch" in build_orientation["warnings"]
    assert build_orientation["evidence_bundle"]["direct_result"] == [
        "evref_recovered_texture_yield_build_orientation_blk-yield-validation",
        "evref_recovered_texture_yield_build_orientation_mechanics_blk-yield-setup",
        "evref_recovered_texture_yield_build_orientation_table_tbl-yield-validation",
    ]
    assert build_orientation["evidence_bundle"]["mechanism"] == [
        "evref_recovered_texture_yield_build_orientation_mechanics_blk-yield-setup"
    ]
    assert build_orientation["evidence_bundle"]["condition_context"] == [
        "evref_recovered_texture_yield_build_orientation_condition_blk-angle-definitions"
    ]
    assert review_queue == []
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    assert "deviations generally less than 5%" in evidence_by_id[
        "evref_recovered_texture_yield_build_orientation_blk-yield-validation"
    ]["quote"]
    assert "363.1" in evidence_by_id[
        "evref_recovered_texture_yield_build_orientation_table_tbl-yield-validation"
    ]["quote"]
    assert "crystallographic texture serving as the primary input" in evidence_by_id[
        "evref_recovered_texture_yield_build_orientation_mechanics_blk-yield-setup"
    ]["quote"]

    persisted = ResearchUnderstanding.from_mapping(
        {
            "state": "limited",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-texture",
                "goal_id": "goal-texture",
                "title": (
                    "How do scan strategy rotation angle and build orientation "
                    "angle affect crystallographic texture and yield strength?"
                ),
            },
            "claims": [
                {
                    "claim_id": (
                        "claim_recovered_texture_yield_prediction_"
                        "blk-yield-validation"
                    ),
                    "claim_type": "finding",
                    "statement": (
                        "Yield strength increased from the 0-0-0 configuration "
                        "to the 45-22.5-0 condition."
                    ),
                    "status": "limited",
                    "confidence": 0.86,
                    "evidence_ref_ids": [
                        "evref_recovered_texture_yield_prediction_"
                        "blk-yield-validation"
                    ],
                    "context_ids": [
                        "ctx_recovered_texture_yield_prediction_"
                        "blk-yield-validation"
                    ],
                    "source_object_ids": ["blk-yield-validation"],
                }
            ],
            "relations": [
                {
                    "relation_id": (
                        "rel_recovered_texture_yield_prediction_"
                        "blk-yield-validation"
                    ),
                    "relation_type": "predict",
                    "subject": "scan strategy rotation angle and build orientation",
                    "predicate": "predict",
                    "object": "crystallographic texture -> yield strength",
                    "statement": (
                        "Yield strength increased from the 0-0-0 configuration "
                        "to the 45-22.5-0 condition."
                    ),
                    "status": "limited",
                    "confidence": 0.86,
                    "evidence_ref_ids": [
                        "evref_recovered_texture_yield_prediction_"
                        "blk-yield-validation"
                    ],
                    "context_ids": [
                        "ctx_recovered_texture_yield_prediction_"
                        "blk-yield-validation"
                    ],
                    "source_object_ids": ["blk-yield-validation"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": (
                        "evref_recovered_texture_yield_prediction_"
                        "blk-yield-validation"
                    ),
                    "source_kind": "paragraph",
                    "document_id": "paper-texture",
                    "label": "3.4. Yield strength prediction and validation",
                    "locator": {
                        "source_ref": "blk-yield-validation",
                        "source_kind": "paragraph",
                        "page": 8,
                    },
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": validation_text,
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_objective_scope",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "scan strategy rotation angle",
                            "build orientation angle",
                        ]
                    },
                    "property_scope": [
                        "crystallographic texture",
                        "yield strength",
                    ],
                },
                {
                    "context_id": (
                        "ctx_recovered_texture_yield_prediction_"
                        "blk-yield-validation"
                    ),
                    "label": "Recovered source scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "scan strategy rotation angle",
                            "build orientation angle",
                        ]
                    },
                    "property_scope": [
                        "crystallographic texture",
                        "yield strength",
                    ],
                },
            ],
        }
    )

    refreshed = service.with_presentation(persisted)

    refreshed_claim_ids = {claim["claim_id"] for claim in refreshed["claims"]}
    assert (
        "claim_recovered_texture_yield_prediction_blk-yield-validation"
        not in refreshed_claim_ids
    )
    assert {
        "claim_recovered_texture_yield_build_orientation_blk-yield-validation",
        "claim_recovered_texture_yield_scan_rotation_blk-yield-validation",
    } <= refreshed_claim_ids
    assert {
        finding["title"] for finding in refreshed["presentation"]["primary_findings"]
    } == {
        "α and β build orientation angles -> yield strength",
        "scan strategy rotation angle -> yield strength",
    }


def test_recovered_finding_alignment_combines_result_and_condition_evidence():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor()
    )
    finding = {
        "claim_id": "claim_recovered_texture_yield_build_orientation_blk-result",
        "variables": ["α and β build orientation angles"],
        "outcomes": ["yield strength"],
        "statement": (
            "Yield strength increased from the 0-0-0 configuration to the "
            "45-22.5-0 condition."
        ),
        "evidence_bundle": {
            "direct_result": ["ev-result"],
            "condition_context": ["ev-condition"],
        },
    }
    evidence_by_id = {
        "ev-result": {
            "source_kind": "paragraph",
            "quote": (
                "Experimental findings show that yield strength increased from "
                "the 0-0-0 configuration to the 45-22.5-0 condition."
            ),
        },
        "ev-condition": {
            "source_kind": "paragraph",
            "quote": (
                "The process used a scan rotation angle θ and build orientation "
                "angles α and β."
            ),
        },
    }

    assert service._finding_has_quote_aligned_direct_result(
        finding,
        evidence_by_id=evidence_by_id,
        blocks_by_id={},
    )
    assert not service._finding_has_quote_aligned_direct_result(
        {
            **finding,
            "evidence_bundle": {
                "direct_result": ["ev-result"],
                "condition_context": [],
            },
        },
        evidence_by_id=evidence_by_id,
        blocks_by_id={},
    )


def test_with_presentation_excludes_unreferenced_evidence_items():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-density",
                    human_readable_id=1,
                    title="Density study",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-density",
                    document_id="paper-density",
                    block_type="paragraph",
                    text="Increasing laser power raised relative density to 99.1%.",
                    block_order=12,
                    page=3,
                    heading_path="3 Results",
                ),
                SourceBlock(
                    block_id="blk-background",
                    document_id="paper-density",
                    block_type="paragraph",
                    text="Background process notes not used by the finding.",
                    block_order=3,
                    page=1,
                    heading_path="1 Introduction",
                ),
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": "How does laser power affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_density",
                    "claim_type": "finding",
                    "statement": "Increasing laser power raised relative density to 99.1%.",
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_density",
                    "relation_type": "increases",
                    "subject": "laser power",
                    "predicate": "increases",
                    "object": "density",
                    "statement": "Increasing laser power raised relative density to 99.1%.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density",
                    "source_kind": "text_window",
                    "document_id": "paper-density",
                    "locator": {"source_ref": "blk-density"},
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "Increasing laser power raised relative density to 99.1%.",
                },
                {
                    "evidence_ref_id": "evref_background",
                    "source_kind": "text_window",
                    "document_id": "paper-density",
                    "locator": {"source_ref": "blk-background"},
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "Background process notes not used by the finding.",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["laser power"]},
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    evidence_item_ids = {
        item["evidence_ref_id"]
        for item in understanding["presentation"]["evidence_items"]
    }
    assert evidence_item_ids == {"evref_density"}


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
    assert understanding["presentation"]["summary"]["evidence_count"] == 1


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


def test_objective_understanding_keeps_comparison_axis_as_relation_subject():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-density",
            "question": "How does laser power affect density under fixed heat treatment?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["laser power", "heat treatment type"],
            "property_axes": ["density"],
        },
        "objective_context": {
            "objective_id": "obj-density",
            "question": "How does laser power affect density under fixed heat treatment?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["laser power", "heat treatment type"],
            "target_property_axes": ["density"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-laser-power",
                "document_id": "paper-1",
                "unit_kind": "comparison",
                "property_normalized": "density",
                "process_context": {
                    "Laser power (W)": "140",
                    "Scan speed (mm/s)": "100",
                    "Type of heat treatment": "Furnace HT",
                },
                "baseline_context": {
                    "source_value_text": "98.45 %",
                    "process_context": {
                        "Laser power (W)": "120",
                        "Scan speed (mm/s)": "100",
                        "Type of heat treatment": "Furnace HT",
                    },
                },
                "value_payload": {
                    "comparison_axis": "laser power",
                    "direction": "decreases",
                    "value": "93.33 %",
                    "controlled_axes": [
                        {"axis": "heat treatment type", "value": "Furnace HT"},
                        {"axis": "scan speed", "value": "100"},
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-density",
                        "evidence_role": "direct_support",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        ],
        "logic_chain": {"evidence_unit_ids": ["oeu-laser-power"]},
    }

    understanding = service.build_objective_understanding(payload)

    relation = next(
        relation
        for relation in understanding["relations"]
        if relation["source_object_ids"] == ["oeu-laser-power"]
    )
    assert relation["subject"] == "laser power"
    finding = _presentation_finding_by_title(understanding, "laser power -> density")
    assert finding["title"] == "laser power -> density"
    assert finding["statement"] == (
        "Selected source table rows show: "
        "With scan speed 100 and heat treatment type Furnace HT, changing "
        "laser power from 120 to 140 decreased density from 98.45 % to 93.33 %. "
        "Expert review is required before treating this as a material effect."
    )
    assert finding["comparison_summary"] == {
        "variable": "laser power",
        "direction": "condition-dependent",
        "outcome": "density",
        "baseline": {
            "label": "laser power=120",
            "value": "98.45 %",
        },
        "observed": {
            "label": "laser power=140",
            "value": "93.33 %",
        },
        "controlled_conditions": [
            {"axis": "scan speed", "value": "100"},
            {"axis": "heat treatment type", "value": "Furnace HT"},
        ],
    }


def test_with_presentation_keeps_controlled_axis_out_of_variable_title():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-fatigue",
                "title": (
                    "How do volumetric energy density and layer thickness "
                    "affect fatigue strength?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_fatigue_strength",
                    "claim_type": "comparison",
                    "statement": (
                        "Under layer thickness 30, volumetric energy density "
                        "increased fatigue strength from 340 MPa (L-VED) to "
                        "450 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_fatigue_strength"],
                    "context_ids": ["ctx_goal", "ctx_fatigue_values"],
                    "source_object_ids": ["oeu-fatigue-strength"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_fatigue_strength",
                    "relation_type": "increases",
                    "subject": "volumetric energy density",
                    "predicate": "increases",
                    "object": "fatigue strength",
                    "statement": (
                        "Under layer thickness 30, volumetric energy density "
                        "increased fatigue strength from 340 MPa (L-VED) to "
                        "450 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_fatigue_strength"],
                    "context_ids": ["ctx_goal", "ctx_fatigue_values"],
                    "source_object_ids": ["oeu-fatigue-strength"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_fatigue_strength",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "Table fatigue",
                    "locator": {"source_ref": "tbl-fatigue"},
                    "fact_ids": ["oeu-fatigue-strength"],
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
                        "variable_process_axes": [
                            "volumetric energy density",
                            "layer thickness",
                        ]
                    },
                    "property_scope": ["fatigue strength"],
                },
                {
                    "context_id": "ctx_fatigue_values",
                    "label": "Claim applicability",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "baseline_context": {
                            "process_context": {
                                "VED [J/mm 3 ]": "50.8",
                                "Layer thickness [ μ m]": "30",
                            },
                            "sample_context": {"Printed 316L": "L-VED"},
                            "source_value_text": "340",
                            "value": 340.0,
                        },
                        "process_context": {
                            "VED [J/mm 3 ]": "79.4",
                            "Layer thickness [ μ m]": "30",
                        },
                        "sample_context": {"Printed 316L": "M-VED"},
                    },
                    "property_scope": ["fatigue strength"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = _presentation_finding_by_claim_id(
        understanding,
        "claim_fatigue_strength",
    )
    assert finding["title"] == "volumetric energy density -> fatigue strength"
    assert finding["variables"] == ["volumetric energy density"]
    assert finding["statement"] == (
        "Selected source table rows show: "
        "With layer thickness 30, changing volumetric energy density "
        "from 50.8 to 79.4 increased fatigue strength from 340 MPa to 450 MPa. "
        "Expert review is required before treating this as a material effect."
    )
    assert finding["comparison_summary"]["controlled_conditions"] == [
        {"axis": "layer thickness", "value": "30"}
    ]


def test_objective_understanding_keeps_controlled_axis_out_of_variable_title():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    payload = {
        "collection_id": "col-1",
        "objective": {
            "objective_id": "obj-fatigue",
            "question": (
                "How do volumetric energy density, laser power, scanning speed, "
                "hatch spacing, and layer thickness affect fatigue strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "process_axes": ["volumetric energy density", "layer thickness"],
            "property_axes": ["fatigue strength"],
        },
        "objective_context": {
            "objective_id": "obj-fatigue",
            "question": (
                "How do volumetric energy density, laser power, scanning speed, "
                "hatch spacing, and layer thickness affect fatigue strength?"
            ),
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": [
                "volumetric energy density",
                "layer thickness",
            ],
            "target_property_axes": ["fatigue strength"],
        },
        "evidence_units": [
            {
                "evidence_unit_id": "oeu-fatigue-strength",
                "document_id": "paper-1",
                "unit_kind": "comparison",
                "property_normalized": "fatigue strength",
                "process_context": {
                    "volumetric_energy_density": "H-VED",
                    "layer_thickness": "30",
                },
                "baseline_context": {
                    "source_value_text": "340 MPa",
                    "process_context": {
                        "volumetric_energy_density": "L-VED",
                        "layer_thickness": "30",
                    },
                },
                "value_payload": {
                    "comparison_axis": "volumetric energy density",
                    "direction": "increases",
                    "value": "450 MPa",
                    "controlled_axes": [{"axis": "layer thickness", "value": "30"}],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "tbl-fatigue",
                        "evidence_role": "direct_support",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.86,
            }
        ],
        "logic_chain": {"evidence_unit_ids": ["oeu-fatigue-strength"]},
    }

    understanding = service.build_objective_understanding(payload)

    relation = next(
        relation
        for relation in understanding["relations"]
        if relation["source_object_ids"] == ["oeu-fatigue-strength"]
    )
    assert relation["subject"] == "volumetric energy density"
    finding = understanding["presentation"]["findings"][0]
    assert finding["title"] == "volumetric energy density -> fatigue strength"
    assert finding["variables"] == ["volumetric energy density"]
    assert finding["comparison_summary"]["controlled_conditions"] == [
        {"axis": "layer thickness", "value": "30"}
    ]


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


def test_with_presentation_backfills_persisted_table_evidence_traceability():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            tables=[
                SourceTable(
                    table_id="table-density",
                    document_id="paper-1",
                    table_order=1,
                    page=6,
                    caption_text="Table 1 Density results.",
                    caption_block_id=None,
                    bbox=None,
                    heading_path="Results",
                    column_headers=["Scan speed", "Density"],
                    table_matrix=[
                        ["Scan speed", "Density"],
                        ["0.175", "93.9"],
                        ["0.239", "96.8"],
                    ],
                )
            ],
        ),
    )
    record = {
        "schema_version": "research_understanding.v1",
        "state": "ready",
        "scope": {
            "scope_type": "goal",
            "collection_id": "col-1",
            "goal_id": "goal-density",
            "title": "How does scan speed affect density?",
        },
        "claims": [
            {
                "claim_id": "claim-density",
                "claim_type": "comparison",
                "statement": "Scan speed 0.239 increased density from 93.9 to 96.8.",
                "status": "limited",
                "confidence": 0.75,
                "evidence_ref_ids": ["evref-density-table"],
            }
        ],
        "relations": [],
        "evidence_refs": [
            {
                "evidence_ref_id": "evref-density-table",
                "source_kind": "table",
                "document_id": "paper-1",
                "label": "P001 Table 1",
                "locator": {
                    "source_ref": "table-density",
                    "source_kind": "table",
                },
                "fact_ids": ["oeu-density"],
                "traceability_status": "resolved",
                "evidence_role": "direct_support",
            }
        ],
        "contexts": [],
        "warnings": [],
    }

    refreshed = service.with_presentation(record)

    evidence_ref = refreshed["evidence_refs"][0]
    assert evidence_ref["locator"]["page"] == 6
    assert evidence_ref["quote"] == (
        "Table 1 Density results. Columns: Scan speed | Density "
        "Rows: Scan speed | Density / 0.175 | 93.9 / 0.239 | 96.8"
    )
    assert evidence_ref["href"].startswith("/collections/col-1/documents/paper-1?")
    assert "source_ref=table-density" in evidence_ref["href"]


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
                "title": "How do LPBF and scanning speed affect density?",
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
                    "process_context": {
                        "variable_process_axes": ["laser power", "scan speed"]
                    },
                    "property_scope": ["relative density", "elongation"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    assert (
        understanding["presentation"]["summary"]["title"]
        == "How do LPBF and scanning speed affect density?"
    )
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
    assert understanding["presentation"]["findings"] == []
    assert understanding["presentation"]["primary_findings"] == []
    assert understanding["presentation"]["review_queue_findings"] == []


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
    assert "quote=Results%20show%20that%20build%20platform%20preheating" in (
        evidence_item["href"] or ""
    )
    assert "improved%20tensile%20strength." in (evidence_item["href"] or "")


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


def test_with_presentation_orders_result_specific_direct_evidence_first():
    abstract_text = (
        "In this study, 316L stainless steel was fabricated by selective laser "
        "melting to evaluate porosity and corrosion behavior."
    )
    result_text = (
        "The electrochemical polarization curves and EIS results revealed that "
        "porosities were highly sensitive to pitting corrosion."
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
                    block_id="blk-abstract",
                    document_id="paper-5",
                    block_type="paragraph",
                    text=abstract_text,
                    block_order=1,
                    page=1,
                    heading_path="Abstract",
                ),
                SourceBlock(
                    block_id="blk-result",
                    document_id="paper-5",
                    block_type="paragraph",
                    text=result_text,
                    block_order=18,
                    page=9,
                    heading_path="Results and discussion",
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
                "title": "How does porosity affect pitting corrosion?",
            },
            "claims": [
                {
                    "claim_id": "claim_corrosion",
                    "claim_type": "finding",
                    "statement": (
                        "Porosities were highly sensitive to pitting corrosion."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": [
                        "evref_abstract",
                        "evref_result",
                    ],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": [
                        "unit_abstract",
                        "unit_result",
                    ],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_porosity_corrosion",
                    "relation_type": "affects",
                    "subject": "porosity level",
                    "predicate": "affects",
                    "object": "pitting corrosion behavior",
                    "statement": (
                        "Porosity level affects pitting corrosion behavior."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": [
                        "evref_abstract",
                        "evref_result",
                    ],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": [
                        "unit_abstract",
                        "unit_result",
                    ],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_abstract",
                    "source_kind": "text_window",
                    "document_id": "paper-5",
                    "label": "P005 Abstract",
                    "locator": {"source_ref": "blk-abstract"},
                    "fact_ids": ["unit_abstract"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
                {
                    "evidence_ref_id": "evref_result",
                    "source_kind": "text_window",
                    "document_id": "paper-5",
                    "label": "P005 Results",
                    "locator": {"source_ref": "blk-result"},
                    "fact_ids": ["unit_result"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
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
    assert finding["evidence_bundle"]["direct_result"] == [
        "evref_result",
        "evref_abstract",
    ]


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


def test_with_presentation_mechanism_quote_statement_prefers_concrete_result_sentence_over_lead_in_quote():
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
    finding = understanding["presentation"]["findings"][0]
    assert finding["statement"] == (
        "Preheating the build platform to 150 C increased the ductility of "
        "material by 14%. This is attributed to the more homogenized "
        "microstructure as well as cellular structure with geometrically "
        "necessary dislocations."
    )
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
    assert evidence_item["source_ref"] == "blk-conclusion-result"
    assert evidence_item["source_text"] == result_text
    assert evidence_item["quote"] == result_text
    assert "source_ref=blk-conclusion-result" in (evidence_item["href"] or "")


def test_with_presentation_filters_measurement_only_density_claim():
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
    assert understanding["presentation"]["findings"] == []
    assert understanding["presentation"]["review_queue_findings"] == []
    results_evidence = next(
        item
        for item in understanding["presentation"]["evidence_items"]
        if item["evidence_ref_id"] == "evref_results"
    )
    assert results_evidence["quote"] == results_text


def test_with_presentation_statement_aligned_quote_prefers_matching_result_sentence():
    ved_text = (
        "It can be noted that the effect of VED was more pronounced between "
        "the LVED and M-VED, showing clear coarsening both in melt pool "
        "average size as well as flattening of melt pool. "
        "The increase in VED from the medium to high level did not notably "
        "affect the melt pool size or grain size, but columnar grains were "
        "observed in the H-VED structure after etching, as is shown as red "
        "dashed lines in Fig. 2c."
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
                    block_id="blk-ved-microstructure",
                    document_id="paper-1",
                    block_type="paragraph",
                    text=ved_text,
                    block_order=65,
                    page=3,
                    heading_path="3.1. As-built microstructures",
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
                "title": "How does VED affect microstructure?",
            },
            "claims": [
                {
                    "claim_id": "claim_ved_microstructure",
                    "claim_type": "finding",
                    "statement": (
                        "The increase in VED from the medium to high level "
                        "did not notably affect the melt pool size or grain "
                        "size, but columnar grains were observed in the H-VED "
                        "structure after etching."
                    ),
                    "status": "supported",
                    "confidence": 0.8,
                    "evidence_ref_ids": ["evref_ved"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_ved"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_ved_microstructure",
                    "relation_type": "affects",
                    "subject": "VED",
                    "predicate": "affects",
                    "object": "microstructure",
                    "statement": "VED affects microstructure.",
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
                    "locator": {"source_ref": "blk-ved-microstructure"},
                    "fact_ids": ["unit_ved"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["VED"]},
                    "property_scope": ["microstructure"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert evidence_item["quote"] == (
        "The increase in VED from the medium to high level did not notably "
        "affect the melt pool size or grain size, but columnar grains were "
        "observed in the H-VED structure after etching, as is shown as red "
        "dashed lines in Fig. 2c."
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
                    "process_context": {
                        "variable_process_axes": ["laser power", "scan speed"]
                    },
                    "property_scope": ["relative density", "elongation"],
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
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id=f"paper-{index}",
                    human_readable_id=index,
                    title=f"Paper {index}",
                    text="",
                )
                for index in range(1, 4)
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
                    "process_context": {
                        "variable_process_axes": ["laser power", "scan speed"]
                    },
                    "property_scope": ["relative density", "elongation"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)
    repeated = service.with_presentation(stored)

    assert understanding is not None
    assert repeated is not None
    finding = understanding["presentation"]["findings"][0]
    assert understanding["presentation"]["summary"]["collection_document_count"] == 3
    assert finding["finding_id"] == "finding_claim_density"
    assert repeated["presentation"]["findings"][0]["finding_id"] == finding["finding_id"]
    assert finding["claim_id"] == "claim_density"
    assert finding["title"] == "laser power -> relative density"
    assert finding["statement"] == "Laser power increases relative density."
    assert finding["variables"] == ["laser power"]
    assert finding["mediators"] == []
    assert finding["outcomes"] == ["relative density"]
    assert finding["direction"] == "increases"
    assert finding["scope_summary"] == "316L stainless steel, laser power, scan speed"
    assert understanding["presentation"]["summary"]["axis_coverage"] == {
        "variables": [
            {
                "axis": "laser power",
                "status": "review_queue",
                "finding_id": "finding_claim_density",
            },
            {
                "axis": "scan speed",
                "status": "context",
                "finding_id": "finding_claim_density",
            },
        ],
        "properties": [
            {
                "axis": "relative density",
                "status": "review_queue",
                "finding_id": "finding_claim_density",
            },
            {"axis": "elongation", "status": "missing", "finding_id": ""},
            {
                "axis": "density",
                "status": "review_queue",
                "finding_id": "finding_claim_density",
            },
        ],
    }
    assert finding["support_grade"] == "partial"
    assert finding["review_status"] == "needs_review"
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
    assert finding["comparison_summary"] is None


def test_with_presentation_compacts_duplicate_uncategorized_evidence_when_direct_exists():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            tables=[
                SourceTable(
                    table_id="table-density",
                    document_id="paper-1",
                    table_order=1,
                    page=4,
                    caption_text=(
                        "Table 2 Experimental conditions and measured density "
                        "for the SLM SS316L samples."
                    ),
                    caption_block_id=None,
                    bbox=None,
                    heading_path="Results",
                    column_headers=["Sample", "Laser power", "Density"],
                    table_matrix=[
                        ["HT1", "100 W", "91.9%"],
                        ["HT2", "150 W", "98.9%"],
                        ["HT3", "200 W", "99.6%"],
                    ],
                )
            ],
        ),
    )
    duplicate_refs = [
        {
            "evidence_ref_id": f"evref_duplicate_{index}",
            "source_kind": "table",
            "document_id": "paper-1",
            "label": "P004 Table 2 density",
            "locator": {"source_ref": "table-density", "page": 4},
            "fact_ids": ["unit_density"],
            "traceability_status": "resolved",
            "quote": "Table 2 measured SLM SS316L sample density.",
        }
        for index in range(4)
    ]
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does heat treatment affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_density",
                    "claim_type": "comparison",
                    "statement": "Heat treatment type changes density.",
                    "status": "supported",
                    "confidence": 0.81,
                    "evidence_ref_ids": [
                        "evref_direct_density",
                        *[
                            duplicate_ref["evidence_ref_id"]
                            for duplicate_ref in duplicate_refs
                        ],
                    ],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_heat_density",
                    "relation_type": "changes",
                    "subject": "heat treatment type",
                    "predicate": "changes",
                    "object": "density",
                    "statement": "Heat treatment type changes density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_direct_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_direct_density",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P004 Table 2 density",
                    "locator": {"source_ref": "table-density", "page": 4},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "quote": (
                        "Table 2 Experimental conditions and measured density "
                        "for the SLM SS316L samples."
                    ),
                    "evidence_role": "direct_support",
                },
                *duplicate_refs,
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["heat treatment type"]},
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_direct_density"]
    assert finding["evidence_bundle"]["uncategorized"] == []
    assert finding["evidence_ref_ids"] == ["evref_direct_density"]
    assert finding["evidence_count"] == 1


def test_with_presentation_compacts_same_source_target_across_bundle_roles():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            tables=[
                SourceTable(
                    table_id="table-density",
                    document_id="paper-1",
                    table_order=1,
                    page=4,
                    caption_text="Table 2 measured density.",
                    caption_block_id=None,
                    bbox=None,
                    heading_path="Results",
                    column_headers=["Sample", "Density"],
                    table_matrix=[["HT1", "98.9%"]],
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
                "title": "How does heat treatment affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_density",
                    "claim_type": "comparison",
                    "statement": "Heat treatment type changes density.",
                    "status": "supported",
                    "confidence": 0.81,
                    "evidence_ref_ids": [
                        "evref_direct_density",
                        "evref_same_table_density",
                    ],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_heat_density",
                    "relation_type": "changes",
                    "subject": "heat treatment type",
                    "predicate": "changes",
                    "object": "density",
                    "statement": "Heat treatment type changes density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_direct_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_direct_density",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P004 Table 2 density",
                    "locator": {"source_ref": "table-density", "page": 4},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "quote": "Table 2 measured density.",
                    "evidence_role": "direct_support",
                },
                {
                    "evidence_ref_id": "evref_same_table_density",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P004 Table 2 density duplicate",
                    "locator": {"source_ref": "table-density", "page": 4},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "quote": "Table 2 measured density.",
                    "evidence_role": "direct_support",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["heat treatment type"]},
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["evidence_bundle"] == {
        "direct_result": ["evref_direct_density"],
        "mechanism": [],
        "condition_context": [],
        "background": [],
        "conflict": [],
        "noise": [],
        "uncategorized": [],
    }
    assert finding["evidence_ref_ids"] == ["evref_direct_density"]
    assert finding["evidence_count"] == 1


def test_with_presentation_evidence_items_follow_visible_findings():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does preheating affect ductility?",
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_ductility",
                    "claim_type": "finding",
                    "statement": "Preheating increases ductility.",
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": [
                        "evref_direct",
                        "evref_stale_background",
                    ],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat"],
                },
                {
                    "claim_id": "claim_noise",
                    "claim_type": "finding",
                    "statement": "The paper describes general LPBF background.",
                    "status": "supported",
                    "confidence": 0.3,
                    "evidence_ref_ids": ["evref_filtered_noise"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_noise"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_ductility",
                    "relation_type": "increases",
                    "subject": "build platform preheating temperature",
                    "predicate": "increases",
                    "object": "ductility",
                    "statement": "Preheating increases ductility.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat"],
                },
                {
                    "relation_id": "rel_noise",
                    "relation_type": "describes",
                    "subject": "background",
                    "predicate": "describes",
                    "object": "literature context",
                    "statement": "The paper describes general LPBF background.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_filtered_noise"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_noise"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_direct",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P002 Results",
                    "locator": {"source_ref": "blk-preheat"},
                    "fact_ids": ["unit_preheat"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Preheating the build platform to 150 °C increased "
                        "the ductility of material by 14%."
                    ),
                },
                {
                    "evidence_ref_id": "evref_stale_background",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P002 Background",
                    "locator": {"source_ref": "blk-background"},
                    "fact_ids": ["unit-background"],
                    "traceability_status": "resolved",
                    "evidence_role": "background",
                    "quote": "This study investigates LPBF 316L.",
                },
                {
                    "evidence_ref_id": "evref_filtered_noise",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P002 Introduction",
                    "locator": {"source_ref": "blk-introduction"},
                    "fact_ids": ["unit_noise"],
                    "traceability_status": "resolved",
                    "evidence_role": "background",
                    "quote": "The aim of this study is to investigate LPBF 316L.",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "build platform preheating temperature"
                        ],
                    },
                    "property_scope": ["ductility"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["primary_findings"][0]
    evidence_items = understanding["presentation"]["evidence_items"]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_direct"]
    assert [item["evidence_ref_id"] for item in evidence_items] == [
        "evref_direct",
        "evref_stale_background",
    ]


def test_with_presentation_filters_boolean_scope_tokens_from_findings():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does preheating affect ductility?",
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_ductility",
                    "claim_type": "finding",
                    "statement": "Preheating increases ductility.",
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_ductility",
                    "relation_type": "increases",
                    "subject": "build platform preheating temperature",
                    "predicate": "increases",
                    "object": "ductility",
                    "statement": "Preheating increases ductility.",
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
                    "label": "P001 Conclusion",
                    "locator": {"source_ref": "blk-preheat"},
                    "fact_ids": ["unit_preheat"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "Preheating increases ductility.",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel", "True"],
                    "process_context": {
                        "build_platform_preheating": "True",
                        "variable_process_axes": [
                            "build platform preheating temperature"
                        ],
                    },
                    "property_scope": ["ductility"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert "True" not in finding["scope_summary"]
    assert "True" not in understanding["presentation"]["summary"]["material_scope"]
    assert "True" not in understanding["presentation"]["summary"]["variable_axes"]


def test_with_presentation_compacts_long_finding_scope_summary():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does VED affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_density",
                    "claim_type": "finding",
                    "statement": "VED increases density.",
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_ved_density",
                    "relation_type": "increases",
                    "subject": "VED",
                    "predicate": "increases",
                    "object": "density",
                    "statement": "VED increases density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "quote": "VED increased density.",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "process": "selective laser melting",
                        "variable_process_axes": ["VED"],
                        "all_conditions": [
                            "laser power",
                            "scan speed",
                            "heat treatment",
                            "as-built condition",
                            "low",
                            "medium",
                            "high",
                            "sample A",
                            "sample B",
                        ],
                    },
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["scope_summary"] == (
        "stainless steel 316L, VED, density, selective laser melting"
    )
    assert "+5 more" not in finding["scope_summary"]


def test_finding_scope_excludes_unrelated_specific_treatment_condition():
    scope_summary = understanding_module._compact_finding_scope_summary(
        "stainless steel 316L, heat treatment type, density, SLM, HIP",
        variables=["heat treatment type"],
        outcomes=["density"],
        statement=(
            "Under laser power 120 and scan speed 280, heat treatment type "
            "Furnace HT increased density from 90.04 % in the untreated "
            "condition to 93.58 %."
        ),
    )

    assert scope_summary == (
        "stainless steel 316L, heat treatment type, density, SLM"
    )

    untreated_scope = understanding_module._compact_finding_scope_summary(
        "stainless steel 316L, scan speed, density, SLM, HIP",
        variables=["scan speed", "energy density"],
        outcomes=["density"],
        statement=(
            "Under heat treatment type - and laser power 100, scan speed "
            "changed from 100 mm/s to 200 mm/s."
        ),
    )

    assert untreated_scope == (
        "stainless steel 316L, scan speed, energy density, density, SLM"
    )

    hip_scope = understanding_module._compact_finding_scope_summary(
        (
            "stainless steel 316L, laser power, density, HIP, "
            "(120/ 200) HIP-SLM, SLM"
        ),
        variables=["laser power", "energy density"],
        outcomes=["density"],
        statement=(
            "Under heat treatment type HIP and scan speed 200, laser power "
            "changed from 100 W to 120 W while energy density changed from "
            "139 J/mm3 to 167 J/mm3."
        ),
    )

    assert hip_scope == (
        "stainless steel 316L, laser power, energy density, density, HIP"
    )
    assert "(120/ 200) HIP-SLM" not in hip_scope


def test_with_presentation_filters_generic_finding_scope_tokens():
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
                    "statement": "Porosities were highly sensitive to pitting corrosion.",
                    "status": "supported",
                    "confidence": 0.86,
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
                    "statement": "Porosity increases pitting corrosion sensitivity.",
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
                    "document_id": "paper-1",
                    "label": "P005 Corrosion results",
                    "locator": {"source_ref": "blk-corrosion"},
                    "fact_ids": ["unit_corrosion"],
                    "traceability_status": "resolved",
                    "quote": (
                        "Porosities were highly sensitive to pitting corrosion."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process": "selective laser melting",
                        "axis_label": "variable",
                    },
                    "test_condition": {"sample_type": "test specimen"},
                    "property_scope": ["pitting corrosion behavior"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["scope_summary"] == (
        "316L stainless steel, porosity level, pitting corrosion behavior, "
        "selective laser melting"
    )
    assert "variable" not in finding["scope_summary"]
    assert "test specimen" not in finding["scope_summary"]


def test_with_presentation_filters_heading_and_broken_sample_scope_tokens():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does heat treatment affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_density",
                    "claim_type": "finding",
                    "statement": "Heat treatment increases density.",
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_density",
                    "relation_type": "increases",
                    "subject": "heat treatment",
                    "predicate": "increases",
                    "object": "density",
                    "statement": "Heat treatment increases density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "quote": "Heat treatment increased density.",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "process": "selective laser melting",
                        "section": "4. Conclusion",
                        "sample": "as-SLM (100/",
                        "treatment": "HIP",
                    },
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["scope_summary"] == (
        "stainless steel 316L, heat treatment, density, selective laser melting, HIP"
    )
    assert "4. Conclusion" not in finding["scope_summary"]
    assert "as-SLM (100/" not in finding["scope_summary"]


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
    assert finding["expert_use_status"] == "review_candidate"
    assert finding["dataset_use_status"] == "review_candidate"
    assert finding["generalization_status"] == "paper_level_only"
    assert (
        finding["generalization_note"]
        == "Evidence comes from one paper; use this as a traceable "
        "paper-level finding, not a cross-paper conclusion."
    )
    assert (
        finding["evidence_gap_summary"]
        == "Needs independent cross-paper confirmation, expert review."
    )
    assert finding["upgrade_actions"] == [
        "verify_direct_evidence",
        "add_cross_paper_evidence",
        "record_expert_review",
    ]


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
    assert understanding["presentation"]["findings"] == []


def test_with_presentation_corrosion_statement_recalls_target_matching_relation_evidence():
    service = ResearchUnderstandingService(
        source_artifact_repository=_FakeSourceArtifactRepository(
            blocks=[
                SourceBlock(
                    block_id="blk-corrosion",
                    document_id="paper-5",
                    block_type="paragraph",
                    text=(
                        "The electrochemical polarization curves and EIS results "
                        "revealed that porosities were highly sensitive to pitting "
                        "corrosion. "
                        "The pitting potential gradually increases with the decreased "
                        "porosity. Meanwhile, higher resistance can slow the corrosion "
                        "rate in the polarization reaction. Therefore, the passive film "
                        "formed on the surface of low porosity sample was more stable "
                        "and exhibited better corrosion properties."
                    ),
                    block_order=1,
                )
            ]
        ),
        structured_extractor=_FakeSemanticExtractor(),
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
                        "Porosities were highly sensitive to pitting corrosion."
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
        "evref_corrosion_text",
        "evref_density_table",
    ]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_corrosion_text"]
    assert finding["evidence_bundle"]["uncategorized"] == ["evref_density_table"]
    assert finding["statement"] == (
        "Across the tested SLM conditions, lower-porosity samples were associated "
        "with higher pitting potential and a more stable passive film, consistent "
        "with better pitting-corrosion resistance. This paper-level evidence does "
        "not isolate porosity as a causal variable."
    )
    assert finding["direction"] == "associated"
    assert "paper_level_association" in finding["warnings"]
    assert finding["support_grade"] == "partial"
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    assert evidence_by_id["evref_corrosion_text"]["quote"] == (
        "The electrochemical polarization curves and EIS results revealed that "
        "porosities were highly sensitive to pitting corrosion. The pitting "
        "potential gradually increases with the decreased porosity. Meanwhile, "
        "higher resistance can slow the corrosion rate in the polarization "
        "reaction. Therefore, the passive film formed on the surface of low "
        "porosity sample was more stable and exhibited better corrosion "
        "properties."
    )


def test_with_presentation_corrosion_statement_keeps_generic_when_mechanism_missing():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())

    statement = service._finding_statement(
        statement="Porosities were highly sensitive to pitting corrosion.",
        variables=["porosity level"],
        outcomes=["pitting corrosion behavior"],
        evidence_by_id={
            "evref_corrosion": {
                "quote": "Porosities were highly sensitive to pitting corrosion.",
                "locator": {"source_ref": "blk-corrosion"},
            }
        },
        evidence_bundle={"direct_result": ["evref_corrosion"]},
        blocks_by_id={},
    )

    assert statement == "Porosities were highly sensitive to pitting corrosion."


def test_with_presentation_corrects_stale_comparison_relation_subject_from_statement():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-density",
                "title": (
                    "How do laser power, scan speed, heat treatment type, and "
                    "heat treatment affect density of stainless steel 316L?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_laser_power_density",
                    "claim_type": "comparison",
                    "statement": (
                        "Under heat treatment type furnace ht and scan speed 100, "
                        "laser power 140 decreased density from 98.45 % "
                        "(laser power 120) to 93.33 %."
                    ),
                    "status": "supported",
                    "confidence": 0.95,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_objective_scope", "ctx_density"],
                    "source_object_ids": ["oeu_laser_power_density"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_stale_heat_treatment_density",
                    "relation_type": "decreases",
                    "subject": "heat treatment",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "Under heat treatment type furnace ht and scan speed 100, "
                        "laser power 140 decreased density from 98.45 % "
                        "(laser power 120) to 93.33 %."
                    ),
                    "status": "supported",
                    "confidence": 0.95,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_density"],
                    "source_object_ids": ["oeu_laser_power_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P004 Table 2 density",
                    "locator": {"source_ref": "table-density"},
                    "evidence_role": "direct_support",
                    "traceability_status": "resolved",
                    "quote": (
                        "Under heat treatment type furnace ht and scan speed 100, "
                        "laser power 140 decreased density from 98.45 % "
                        "(laser power 120) to 93.33 %."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_objective_scope",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "variable_process_axes": [
                            "laser power",
                            "scan speed",
                            "heat treatment type",
                            "heat treatment",
                        ]
                    },
                    "property_scope": ["density"],
                },
                {
                    "context_id": "ctx_density",
                    "label": "Evidence context",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "laser_power": "140",
                        "scan_speed": "100",
                        "heat_treatment_type": "Furnace HT",
                    },
                    "property_scope": ["density"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    finding = _presentation_finding_by_title(understanding, "laser power -> density")
    assert finding["title"] == "laser power -> density"
    assert finding["variables"] == ["laser power"]
    assert finding["relation_chain"][0]["variable"] == "laser power"
    assert "laser power 140 decreased density" in finding["statement"]


def test_with_presentation_does_not_promote_controlled_axis_to_comparison_subject():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-density",
                "title": (
                    "How do laser power, scan speed, heat treatment type, and "
                    "heat treatment affect density of stainless steel 316L?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_heat_treatment_type_density",
                    "claim_type": "comparison",
                    "statement": (
                        "Under laser power 140 and scan speed 100, heat "
                        "treatment type Furnace HT increased density from "
                        "98.16 % (heat treatment type HIP) to 99.33 %."
                    ),
                    "status": "supported",
                    "confidence": 0.95,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_objective_scope", "ctx_density"],
                    "source_object_ids": ["oeu_heat_treatment_type_density"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_heat_treatment_type_density",
                    "relation_type": "increases",
                    "subject": "heat treatment",
                    "predicate": "increases",
                    "object": "density",
                    "statement": (
                        "Under laser power 140 and scan speed 100, heat "
                        "treatment type Furnace HT increased density from "
                        "98.16 % (heat treatment type HIP) to 99.33 %."
                    ),
                    "status": "supported",
                    "confidence": 0.95,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_density"],
                    "source_object_ids": ["oeu_heat_treatment_type_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P004 Table 2 density",
                    "locator": {"source_ref": "table-density"},
                    "evidence_role": "direct_support",
                    "traceability_status": "resolved",
                    "quote": (
                        "Under laser power 140 and scan speed 100, heat "
                        "treatment type Furnace HT increased density from "
                        "98.16 % (heat treatment type HIP) to 99.33 %."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_objective_scope",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "variable_process_axes": [
                            "laser power",
                            "scan speed",
                            "heat treatment type",
                            "heat treatment",
                        ]
                    },
                    "property_scope": ["density"],
                },
                {
                    "context_id": "ctx_density",
                    "label": "Evidence context",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "laser_power": "140",
                        "scan_speed": "100",
                        "heat_treatment_type": "Furnace HT",
                    },
                    "property_scope": ["density"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    finding = _presentation_finding_by_title(
        understanding,
        "heat treatment type -> density",
    )
    assert finding["title"] == "heat treatment type -> density"
    assert finding["variables"] == ["heat treatment type"]
    assert finding["relation_chain"][0]["variable"] == "heat treatment type"
    assert "heat treatment type Furnace HT increased density" in finding["statement"]


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


def test_with_presentation_filters_claim_and_evidence_recalibrated_off_axis_relation():
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
                {
                    "relation_id": "rel_preheat_grain_coarsening",
                    "relation_type": "increases",
                    "subject": "build platform preheating",
                    "predicate": "increases",
                    "object": "grain coarsening",
                    "statement": (
                        "Build platform preheating increases grain coarsening."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_ved_grains"],
                    "context_ids": ["ctx_ved_grains"],
                    "source_object_ids": ["unit_ved_grains"],
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
                {
                    "evidence_ref_id": "evref_ved_grains",
                    "source_kind": "text_window",
                    "document_id": "paper-3",
                    "label": "P003 VED result",
                    "locator": {"source_ref": "blk-ved-grains"},
                    "fact_ids": ["unit_ved_grains"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Grain size increased from 81 to 115 um as VED increased "
                        "from 50.8 to 84 J/mm3."
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
                {
                    "context_id": "ctx_ved_grains",
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
    ]
    assert findings[0]["title"] == "build platform preheating -> microstructure"
    assert findings[0]["variables"] == ["build platform preheating"]
    assert findings[0]["evidence_bundle"]["direct_result"] == ["evref_preheat"]
    assert findings[0]["support_grade"] == "partial"


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
        "claim_conflict": "conflict",
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
        "build platform preheating temperature -> ductility"
    )
    assert finding["variables"] == ["build platform preheating temperature"]
    assert finding["mediators"] == ["microstructure"]
    assert finding["outcomes"] == ["ductility"]
    assert finding["relation_chain"] == [
        {
            "relation_id": "rel_preheat_mechanical",
            "variable": "build platform preheating temperature",
            "mediators": ["microstructure"],
            "outcome": "ductility",
            "direction": "improves",
            "statement": (
                "Higher build platform preheating temperature improves "
                "mechanical properties by modifying microstructure."
            ),
        }
    ]


def test_with_presentation_projects_mechanism_claim_terms_to_mediators():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    statement = (
        "Preheating the build plate increased the El% and yield strength ( ı y) "
        "of the material by approximately 14% and 4%, respectively. This is "
        "attributed to the microstructure and texture evolution."
    )
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
                    "claim_id": "claim_preheat_mechanism",
                    "claim_type": "mechanism",
                    "statement": statement,
                    "status": "supported",
                    "confidence": 0.88,
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_microstructure",
                    "relation_type": "mechanistic",
                    "subject": "build platform preheating",
                    "predicate": "explains",
                    "object": "microstructure evolution",
                    "statement": statement,
                    "status": "supported",
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct"],
                },
                {
                    "relation_id": "rel_mechanical",
                    "relation_type": "mechanistic",
                    "subject": "build platform preheating",
                    "predicate": "explains",
                    "object": "microstructure evolution -> mechanical properties",
                    "statement": statement,
                    "status": "supported",
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct"],
                },
                {
                    "relation_id": "rel_texture",
                    "relation_type": "mechanistic",
                    "subject": "build platform preheating",
                    "predicate": "explains",
                    "object": "texture evolution",
                    "statement": statement,
                    "status": "supported",
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_direct",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_direct"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": statement,
                }
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
    finding = understanding["presentation"]["findings"][0]
    assert finding["title"] == (
        "build platform preheating -> ductility and yield strength"
    )
    assert finding["mediators"] == [
        "microstructure evolution",
        "texture evolution",
    ]
    assert finding["outcomes"] == ["ductility", "yield strength"]
    assert finding["statement"] == (
        "Build platform preheating increased elongation by approximately 14% "
        "and yield strength by approximately 4%; the authors attributed both "
        "changes to microstructure and texture evolution."
    )
    assert all(
        segment["statement"] == finding["statement"]
        for segment in finding["relation_chain"]
    )
    assert "author_attributed_mechanism" in finding["warnings"]
    assert "author_attributed_mechanism" in finding["review_reasons"]
    assert "ı" not in finding["statement"]
    assert not {
        "microstructure evolution",
        "texture evolution",
    } & {segment["outcome"] for segment in finding["relation_chain"]}


def test_direct_evidence_preserves_explicit_microstructure_and_texture_mechanisms():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())

    mediators = service._finding_mediators_from_direct_evidence(
        "The increases in elongation and yield strength were attributed to the "
        "microstructure and texture evolution."
    )

    assert mediators == ["microstructure evolution", "texture evolution"]


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
    ]
    assert findings[0]["support_grade"] == "partial"
    assert findings[0]["evidence_bundle"]["direct_result"] == ["evref_direct"]
    assert findings[0]["review_reasons"] == [
        "single_paper_evidence",
        "needs_cross_paper_confirmation",
        "partial_support",
        "missing_mechanism_evidence",
        "needs_expert_review",
    ]
    assert len(findings) == 1
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    assert set(evidence_by_id) == {"evref_direct"}
    direct_href = evidence_by_id["evref_direct"]["href"] or ""
    assert direct_href.startswith(
        "/collections/col-1/documents/paper-1"
        "?view=parsed-paper&source_ref=blk-results"
    )
    assert "quote=Preheating%20increased%20ductility%20by%2014%25." in direct_href
    assert understanding["presentation"]["primary_findings"] == [findings[0]]
    assert understanding["presentation"]["review_queue_findings"] == []
    assert (
        understanding["presentation"]["summary"]["primary_finding_count"]
        == 1
    )
    assert (
        understanding["presentation"]["summary"]["review_queue_finding_count"]
        == 0
    )
    assert understanding["presentation"]["summary"]["evidence_count"] == 1
    assert understanding["presentation"]["summary"]["evidence_count"] == len(
        understanding["presentation"]["evidence_items"]
    )

    response_payload = ResearchUnderstandingResponse.model_validate(
        understanding
    ).model_dump()
    serialized_primary = response_payload["presentation"]["primary_findings"]
    serialized_review = response_payload["presentation"][
        "review_queue_findings"
    ]
    assert [finding["finding_id"] for finding in serialized_primary] == [
        findings[0]["finding_id"]
    ]
    assert serialized_review == []
    assert serialized_primary[0]["support_grade"] == "partial"
    assert serialized_primary[0]["evidence_bundle"]["direct_result"] == [
        "evref_direct"
    ]
    assert serialized_primary[0]["relation_chain"] == findings[0]["relation_chain"]
    assert serialized_primary[0]["generalization_status"] == "paper_level_only"
    assert (
        serialized_primary[0]["generalization_note"]
        == "Evidence comes from one paper; use this as a traceable "
        "paper-level finding, not a cross-paper conclusion."
    )
    assert (
        serialized_primary[0]["evidence_gap_summary"]
        == "Needs independent cross-paper confirmation, support-grade curation, expert review."
    )
    assert serialized_primary[0]["review_reasons"] == [
        "single_paper_evidence",
        "needs_cross_paper_confirmation",
        "partial_support",
        "missing_mechanism_evidence",
        "needs_expert_review",
    ]
    serialized_evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in response_payload["presentation"]["evidence_items"]
    }
    assert set(serialized_evidence_by_id) == {"evref_direct"}
    serialized_direct_href = serialized_evidence_by_id["evref_direct"]["href"] or ""
    assert serialized_direct_href.startswith(
        "/collections/col-1/documents/paper-1"
        "?view=parsed-paper&source_ref=blk-results"
    )
    assert (
        "quote=Preheating%20increased%20ductility%20by%2014%25."
        in serialized_direct_href
    )
    assert (
        response_payload["presentation"]["summary"][
            "primary_finding_count"
        ]
        == 1
    )
    assert (
        response_payload["presentation"]["summary"][
            "review_queue_finding_count"
        ]
        == 0
    )


def test_with_presentation_quote_mismatched_finding_is_not_expert_finding():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does preheating affect microstructure?",
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_microstructure",
                    "claim_type": "finding",
                    "statement": (
                        "Preheating changes microstructure through residual stress."
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
                    "relation_id": "rel_preheat_microstructure",
                    "relation_type": "reduces",
                    "subject": "build platform preheating temperature",
                    "predicate": "reduces",
                    "object": "residual stress -> microstructure",
                    "statement": (
                        "Higher build platform preheating temperature reduces "
                        "residual stress and changes microstructure."
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
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_direct"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Preheating the build platform to 150 C increased "
                        "ductility by 14% and yield strength by 4%."
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
    assert understanding["presentation"]["findings"] == []
    assert understanding["presentation"]["primary_findings"] == []
    assert understanding["presentation"]["review_queue_findings"] == []


def test_with_presentation_does_not_report_missing_mechanism_when_direct_evidence_contains_mechanism():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            blocks=[
                SourceBlock(
                    block_id="blk-results",
                    document_id="paper-1",
                    block_type="paragraph",
                    text=(
                        "Heat treatment increased density and removed porosity. "
                        "The cellular microstructure and dense dislocation "
                        "structures disappeared after short heat treatments "
                        "owing to recrystallization."
                    ),
                    block_order=12,
                    page=12,
                    heading_path="4. Conclusion",
                )
            ]
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does heat treatment affect density and microstructure?",
            },
            "claims": [
                {
                    "claim_id": "claim_heat_density",
                    "claim_type": "finding",
                    "statement": (
                        "Heat treatment increased density and changed "
                        "microstructure through recrystallization."
                    ),
                    "status": "supported",
                    "confidence": 0.88,
                    "evidence_ref_ids": ["evref_direct"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_direct"],
                    "warnings": ["needs_expert_review"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_heat_density",
                    "relation_type": "compares",
                    "subject": "heat treatment",
                    "predicate": "compares",
                    "object": "cellular microstructure -> density and microstructure",
                    "statement": (
                        "Heat treatment changes density and microstructure "
                        "through cellular microstructure evolution."
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
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_direct"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "The cellular microstructure and dense dislocation "
                        "structures disappeared after short heat treatments "
                        "owing to recrystallization."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["heat treatment"]},
                    "property_scope": ["density", "microstructure"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = _presentation_review_finding_by_claim_id(
        understanding,
        "claim_heat_density",
    )
    assert finding["evidence_bundle"]["direct_result"] == ["evref_direct"]
    assert finding["evidence_bundle"]["mechanism"] == ["evref_direct"]
    assert finding["evidence_ref_ids"] == ["evref_direct"]
    assert "cellular microstructure" in finding["mediators"]
    assert "recrystallization" in finding["mediators"]
    assert "missing_mechanism_evidence" not in finding["review_reasons"]


def test_with_presentation_quote_aligned_primary_finding_stays_primary():
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
                    "claim_id": "claim_porosity_corrosion",
                    "claim_type": "finding",
                    "statement": (
                        "Porosity level and pore size affect pitting corrosion "
                        "behavior."
                    ),
                    "status": "supported",
                    "confidence": 0.9,
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
                        "Porosity level increases susceptibility to pitting "
                        "corrosion behavior."
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
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_corrosion"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "The electrochemical polarization curves revealed "
                        "that porosity was highly sensitive to pitting corrosion."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["porosity level"]
                    },
                    "property_scope": ["pitting corrosion behavior"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["support_grade"] == "partial"
    assert understanding["presentation"]["primary_findings"] == [finding]
    assert understanding["presentation"]["review_queue_findings"] == []


def test_with_presentation_uses_numeric_relation_statement_for_symbol_axis_finding():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How do angle axes affect yield strength?",
            },
            "claims": [
                {
                    "claim_id": "claim_theta_yield",
                    "claim_type": "comparison",
                    "statement": "θ is associated with yield strength experiment.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_boundary"],
                    "source_object_ids": ["oeu_cmp_theta"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_theta_yield",
                    "relation_type": "increases",
                    "subject": "θ",
                    "predicate": "increases",
                    "object": "yield strength experiment",
                    "statement": (
                        "Under α 0 and β 0, θ increased yield strength experiment "
                        "from 334.2 MPa to 342.5 MPa."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_boundary"],
                    "source_object_ids": ["oeu_cmp_theta"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_table",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "locator": {"source_ref": "table-angles"},
                    "fact_ids": ["oeu_cmp_theta"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_boundary",
                    "label": "Claim applicability",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process_context": {"α": "0", "β": "0", "θ": "30"},
                    },
                    "property_scope": ["yield strength experiment"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = _presentation_finding_by_claim_id(
        understanding,
        "claim_theta_yield",
    )
    assert finding["statement"] == (
        "Selected source table rows show: "
        "Under α 0 and β 0, θ increased yield strength experiment "
        "from 334.2 MPa to 342.5 MPa. "
        "Expert review is required before treating this as a material effect."
    )
    assert finding["title"] == (
        "scan strategy rotation angle -> yield strength experiment"
    )


def test_with_presentation_comparison_summary_handles_symbol_conditions():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How do angle axes affect yield strength?",
            },
            "claims": [
                {
                    "claim_id": "claim_theta_yield",
                    "claim_type": "comparison",
                    "statement": "θ is associated with yield strength experiment.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_boundary"],
                    "source_object_ids": ["oeu_cmp_theta"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_theta_yield",
                    "relation_type": "decreases",
                    "subject": "β",
                    "predicate": "decreases",
                    "object": "yield strength experiment",
                    "statement": (
                        "Under ɵ=0, α=0 and θ=0, β decreased yield strength "
                        "experiment from 334.2 MPa (1) to 295.1 MPa."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_boundary"],
                    "source_object_ids": ["oeu_cmp_theta"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_table",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "locator": {"source_ref": "table-angles"},
                    "fact_ids": ["oeu_cmp_theta"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_boundary",
                    "label": "Claim applicability",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process_context": {"α": "0", "β": "90", "θ": "0"},
                    },
                    "property_scope": ["yield strength experiment"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = _presentation_finding_by_claim_id(
        understanding,
        "claim_theta_yield",
    )
    assert finding["comparison_summary"] == {
        "variable": "β build orientation angle",
        "direction": "condition-dependent",
        "outcome": "yield strength experiment",
        "baseline": {"label": "1", "value": "334.2 MPa"},
        "observed": {"label": "β", "value": "295.1 MPa"},
        "controlled_conditions": [
            {"axis": "scan strategy rotation angle", "value": "0"},
            {"axis": "α build orientation angle", "value": "0"},
        ],
    }
    assert "β build orientation angle" in finding["scope_summary"]
    assert "α build orientation angle" not in finding["scope_summary"]


def test_with_presentation_rewrites_stored_symbol_comparison_with_axis_values():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does build orientation affect yield strength?",
            },
            "claims": [
                {
                    "claim_id": "claim_beta_prediction",
                    "claim_type": "comparison",
                    "statement": (
                        "Under ɵ=0, α=0 and θ=0, β increased yield strength "
                        "prediction from 310.48 MPa (1) to 314.37 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.62,
                    "evidence_ref_ids": ["evref_beta_prediction"],
                    "context_ids": ["ctx_beta_prediction"],
                    "source_object_ids": ["oeu_cmp_beta_prediction"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_beta_prediction",
                    "relation_type": "increases",
                    "subject": "scan strategy rotation angle",
                    "predicate": "increases",
                    "object": "yield strength prediction",
                    "statement": (
                        "Under ɵ=0, α=0 and θ=0, β increased yield strength "
                        "prediction from 310.48 MPa (1) to 314.37 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.62,
                    "evidence_ref_ids": ["evref_beta_prediction"],
                    "context_ids": ["ctx_beta_prediction"],
                    "source_object_ids": ["oeu_cmp_beta_prediction"],
                    "warnings": ["deterministic_relation"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_beta_prediction",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "locator": {"source_ref": "table-angles"},
                    "fact_ids": ["oeu_cmp_beta_prediction"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_objective_scope",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "scan strategy rotation angle",
                            "build orientation angle",
                        ]
                    },
                    "property_scope": ["yield strength"],
                },
                {
                    "context_id": "ctx_beta_prediction",
                    "label": "Claim applicability",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "baseline_context": {
                            "process_context": {
                                "ɵ ( ◦ )": "0",
                                "α ( ◦ )": "0",
                                "β ( ◦ )": "0",
                                "θ ( ◦ )": "0",
                            },
                            "sample_context": {"sample_number": "1"},
                            "source_value_text": "310.48",
                        },
                        "process_context": {
                            "ɵ ( ◦ )": "0",
                            "α ( ◦ )": "0",
                            "β ( ◦ )": "22.5",
                            "θ ( ◦ )": "0",
                        },
                        "sample_context": {"sample_number": "4"},
                    },
                    "property_scope": ["yield strength prediction"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    assert understanding["presentation"]["findings"] == []
    assert understanding["presentation"]["review_queue_findings"] == []


def test_with_presentation_comparison_summary_handles_uncertainty_parentheses():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does energy density affect elongation?",
            },
            "claims": [
                {
                    "claim_id": "claim_energy_elongation",
                    "claim_type": "comparison",
                    "statement": (
                        "Under scanning speed 100, energy density 333 decreased "
                        "elongation from 52.7 ( ± 3.6) % (energy density 278) "
                        "to 35.0 %."
                    ),
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_boundary"],
                    "source_object_ids": ["oeu_cmp_energy"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_energy_elongation",
                    "relation_type": "decreases",
                    "subject": "energy density",
                    "predicate": "decreases",
                    "object": "elongation",
                    "statement": (
                        "Under scanning speed 100, energy density 333 decreased "
                        "elongation from 52.7 ( ± 3.6) % (energy density 278) "
                        "to 35.0 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_boundary"],
                    "source_object_ids": ["oeu_cmp_energy"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_table",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "locator": {"source_ref": "table-energy"},
                    "fact_ids": ["oeu_cmp_energy"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_boundary",
                    "label": "Claim applicability",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process_context": {
                            "energy density": "333",
                            "scanning speed": "100",
                        },
                    },
                    "property_scope": ["elongation"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = _presentation_finding_by_claim_id(
        understanding,
        "claim_energy_elongation",
    )
    assert finding["comparison_summary"] == {
        "variable": "energy density",
        "direction": "condition-dependent",
        "outcome": "elongation",
        "baseline": {
            "label": "energy density 278",
            "value": "52.7 ( ± 3.6) %",
        },
        "observed": {"label": "energy density 333", "value": "35.0 %"},
        "controlled_conditions": [{"axis": "scanning speed", "value": "100"}],
    }
    assert finding["evidence_bundle"]["direct_result"] == ["evref_table"]
    _presentation_review_finding_by_claim_id(
        understanding,
        "claim_energy_elongation",
    )


def test_with_presentation_keeps_table_row_comparison_in_review_when_narrative_primary_exists():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": (
                    "How do scanning speed and energy density affect yield "
                    "strength and elongation?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_scan_speed_mechanics",
                    "claim_type": "finding",
                    "statement": (
                        "Higher scanning speed produced better densification, "
                        "refined microstructure, and excellent mechanical "
                        "properties."
                    ),
                    "status": "supported",
                    "confidence": 0.92,
                    "evidence_ref_ids": ["evref_narrative"],
                    "context_ids": ["ctx_boundary"],
                    "source_object_ids": ["oeu_scan_speed"],
                },
                {
                    "claim_id": "claim_energy_elongation",
                    "claim_type": "comparison",
                    "statement": (
                        "Under scanning speed 100, energy density 333 decreased "
                        "elongation from 52.7 ( ± 3.6) % (energy density 278) "
                        "to 35.0 %."
                    ),
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_boundary"],
                    "source_object_ids": ["oeu_cmp_energy"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_scan_speed_mechanics",
                    "relation_type": "affects",
                    "subject": "scanning speed",
                    "predicate": "affects",
                    "object": "mechanical properties",
                    "statement": (
                        "Higher scanning speed produced better densification, "
                        "refined microstructure, and excellent mechanical "
                        "properties."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_narrative"],
                    "context_ids": ["ctx_boundary"],
                    "source_object_ids": ["oeu_scan_speed"],
                },
                {
                    "relation_id": "rel_energy_elongation",
                    "relation_type": "decreases",
                    "subject": "energy density",
                    "predicate": "decreases",
                    "object": "elongation",
                    "statement": (
                        "Under scanning speed 100, energy density 333 decreased "
                        "elongation from 52.7 ( ± 3.6) % (energy density 278) "
                        "to 35.0 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_boundary"],
                    "source_object_ids": ["oeu_cmp_energy"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_narrative",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "locator": {"source_ref": "blk-scan-speed"},
                    "fact_ids": ["oeu_scan_speed"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "The SLM samples processed at higher scanning speed "
                        "exhibited better densification, refined microstructure, "
                        "and excellent mechanical properties."
                    ),
                },
                {
                    "evidence_ref_id": "evref_table",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "locator": {"source_ref": "table-energy"},
                    "fact_ids": ["oeu_cmp_energy"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_boundary",
                    "label": "Claim applicability",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process_context": {
                            "energy density": "333",
                            "scanning speed": "100",
                        },
                        "variable_process_axes": [
                            "scanning speed",
                            "energy density",
                        ],
                    },
                    "property_scope": [
                        "yield strength",
                        "ultimate tensile strength",
                        "elongation",
                    ],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = _presentation_finding_by_claim_id(
        understanding,
        "claim_energy_elongation",
    )
    assert finding["comparison_summary"] == {
        "variable": "energy density",
        "direction": "condition-dependent",
        "outcome": "elongation",
        "baseline": {
            "label": "energy density 278",
            "value": "52.7 ( ± 3.6) %",
        },
        "observed": {"label": "energy density 333", "value": "35.0 %"},
        "controlled_conditions": [{"axis": "scanning speed", "value": "100"}],
    }
    assert finding["evidence_bundle"]["direct_result"] == ["evref_table"]
    _presentation_review_finding_by_claim_id(
        understanding,
        "claim_energy_elongation",
    )
    assert finding["review_status"] == "needs_review"
    assert finding["generalization_status"] == "paper_level_only"


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
    assert finding["relation_chain"][0]["variable"] == "VED"
    assert finding["relation_chain"][0]["direction"] == "explains"


def test_with_presentation_relation_chain_uses_each_display_variable():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How do defects affect pitting corrosion?",
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
                    "confidence": 0.9,
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
                        "Porosity level increases susceptibility to pitting "
                        "corrosion behavior."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_corrosion"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_corrosion"],
                },
                {
                    "relation_id": "rel_pore_corrosion",
                    "relation_type": "increases",
                    "subject": "pore size",
                    "predicate": "increases",
                    "object": "pitting corrosion behavior",
                    "statement": (
                        "Pore size increases susceptibility to pitting "
                        "corrosion behavior."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_corrosion"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_corrosion"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_corrosion",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_corrosion"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Porosity level and pore size were highly sensitive "
                        "to pitting corrosion behavior."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["porosity level", "pore size"]
                    },
                    "property_scope": ["pitting corrosion behavior"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["variables"] == ["porosity level", "pore size"]
    assert [
        segment["variable"] for segment in finding["relation_chain"]
    ] == ["porosity level", "pore size"]


def test_with_presentation_specific_outcomes_narrows_mechanical_properties():
    service = ResearchUnderstandingService(
        source_artifact_repository=_FakeSourceArtifactRepository(
            blocks=[
                SourceBlock(
                    block_id="blk-results",
                    document_id="paper-1",
                    block_type="paragraph",
                    text=(
                        "Preheating the build platform to 150 C increased the "
                        "ductility of material by 14%."
                    ),
                    block_order=1,
                )
            ]
        ),
        structured_extractor=_FakeSemanticExtractor(),
    )
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
                    "statement": (
                        "Higher build platform preheating temperature improves "
                        "mechanical properties."
                    ),
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
                    "statement": (
                        "Higher build platform preheating temperature improves "
                        "mechanical properties."
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
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_preheat"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "Preheating changed mechanical properties.",
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
    assert finding["outcomes"] == ["ductility"]
    assert finding["title"] == "build platform preheating temperature -> ductility"
    assert finding["statement"] == (
        "Preheating the build platform to 150 C increased the ductility of material by 14%."
    )


def test_with_presentation_mechanism_quote_statement_keeps_result_only_without_attribution():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does VED affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_density",
                    "claim_type": "finding",
                    "statement": "VED increases density.",
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_density",
                    "relation_type": "increases",
                    "subject": "VED",
                    "predicate": "increases",
                    "object": "density",
                    "statement": "VED increases density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-density"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "The achieved density measured using the Archimedes "
                        "method was 91.9, 98.9 and 99.6% for L-VED, M-VED "
                        "and H-VED, respectively. The samples were then used "
                        "for fatigue testing."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"process": "selective laser melting"},
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["statement"] == (
        "The achieved density measured using the Archimedes method was 91.9, "
        "98.9 and 99.6% for L-VED, M-VED and H-VED, respectively."
    )


def test_with_presentation_specific_outcomes_keeps_broad_bucket_without_property_hit():
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
                    "statement": "Build platform preheating changes mechanical properties.",
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
                    "relation_type": "affects",
                    "subject": "build platform preheating temperature",
                    "predicate": "affects",
                    "object": "mechanical properties",
                    "statement": "Build platform preheating changes mechanical properties.",
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
                    "quote": "Build platform preheating changed mechanical properties.",
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
    assert finding["outcomes"] == ["mechanical properties"]
    assert finding["title"] == (
        "build platform preheating temperature -> mechanical properties"
    )


def test_specific_quote_statement_preserves_equivalent_aligned_statement():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())

    statement = service._finding_statement(
        statement="Laser power increases relative density.",
        variables=["laser power"],
        outcomes=["relative density"],
        evidence_by_id={
            "evref_density": {
                "quote": "Relative density increased with laser power.",
                "locator": {},
            }
        },
        evidence_bundle={"direct_result": ["evref_density"]},
        blocks_by_id={},
    )

    assert statement == "Laser power increases relative density."


def test_with_presentation_does_not_promote_density_measurements_to_finding():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does energy density affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_ved_density",
                    "claim_type": "finding",
                    "statement": (
                        "Changes in laser power and scan speed affect porosity, "
                        "which in turn influences relative density."
                    ),
                    "status": "supported",
                    "confidence": 0.95,
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                    "needs_review": True,
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_density",
                    "relation_type": "increases",
                    "subject": "laser power and scan speed",
                    "predicate": "increases",
                    "object": "porosity -> density",
                    "statement": (
                        "Changes in laser power and scan speed affect porosity, "
                        "which in turn influences relative density."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-results"},
                    "fact_ids": ["unit_density"],
                    "traceability_status": "resolved",
                    "quote": (
                        "The achieved density measured using the Archimedes "
                        "method was 91.9, 98.9 and 99.6% for L-VED, M-VED "
                        "and H-VED, respectively."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["laser power", "scan speed"]
                    },
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    assert understanding["presentation"]["findings"] == []
    assert understanding["presentation"]["primary_findings"] == []
    assert understanding["presentation"]["review_queue_findings"] == []
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert evidence_item["quote"] == (
        "The achieved density measured using the Archimedes method was "
        "91.9, 98.9 and 99.6% for L-VED, M-VED and H-VED, respectively."
    )


def test_with_presentation_quote_derived_statement_uses_microstructure_result():
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
                    "statement": "Selective laser melting affects the as-built structure.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_ved"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_ved"],
                    "needs_review": True,
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_slm_microstructure",
                    "relation_type": "affects",
                    "subject": "selective laser melting",
                    "predicate": "affects",
                    "object": "microstructure",
                    "statement": "Selective laser melting affects the as-built structure.",
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
                        "not notably affect the melt pool size or grain size, "
                        "but columnar grains were observed in the H-VED structure "
                        "after etching, as is shown in Fig. 2c."
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
    assert finding["statement"] == (
        "The increase in VED from the medium to high level did not notably "
        "affect the melt pool size or grain size, but columnar grains were "
        "observed in the H-VED structure after etching, as is shown in Fig. 2c."
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
    assert understanding["presentation"]["findings"] == []


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
    assert understanding["presentation"]["findings"] == []
    assert understanding["presentation"]["primary_findings"] == []
    assert understanding["presentation"]["review_queue_findings"] == []


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


def test_with_presentation_recovers_empty_goal_finding_from_source_blocks():
    source_text = (
        "As pointed out, the defects in PBF-LB materials results in low fatigue "
        "resistance compared to their static properties. The present results "
        "indicate that the increasing VED leads to lower fraction of defects, "
        "slightly smaller defect size and complexity, and improves slightly the "
        "fatigue life. The fatigue limit is still limited by remaining LoF "
        "defects."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-fatigue",
                    human_readable_id=3,
                    title="VED effects on defect structure and fatigue behaviour",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-fatigue-result",
                    document_id="paper-fatigue",
                    block_type="paragraph",
                    text=source_text,
                    block_order=139,
                    page=10,
                    heading_path="4.2. The influence of defect structure on fatigue strength",
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "empty",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-fatigue",
                "goal_id": "goal-fatigue",
                "title": (
                    "How do volumetric energy density, laser power, scanning "
                    "speed, hatch spacing, and layer thickness affect defect "
                    "structure and fatigue strength of 316L stainless steel "
                    "processed via laser beam powder bed fusion?"
                ),
            },
            "claims": [],
            "relations": [],
            "evidence_refs": [],
            "contexts": [],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    assert understanding["state"] == "limited"
    primary = understanding["presentation"]["primary_findings"]
    assert len(primary) == 1
    assert primary[0]["title"] == "VED -> fatigue strength"
    assert primary[0]["direction"] != "reduces"
    assert primary[0]["relation_chain"][0]["direction"] != "reduces"
    assert primary[0]["evidence_bundle"]["direct_result"] == [
        "evref_recovered_ved_defects_fatigue_blk-fatigue-result"
    ]
    evidence_by_id = {
        ref["evidence_ref_id"]: ref for ref in understanding["evidence_refs"]
    }
    claim_by_id = {claim["claim_id"]: claim for claim in understanding["claims"]}
    relation_by_id = {
        relation["relation_id"]: relation
        for relation in understanding["relations"]
    }
    context_by_id = {
        context["context_id"]: context for context in understanding["contexts"]
    }
    assert primary[0]["claim_id"] in claim_by_id
    assert primary[0]["relation_ids"][0] in relation_by_id
    assert primary[0]["context_ids"][0] in context_by_id
    assert primary[0]["evidence_ref_ids"][0] in evidence_by_id
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert evidence_item["source_ref"] == "blk-fatigue-result"
    assert evidence_item["page"] == "10"
    assert "lower fraction of defects" in evidence_item["quote"]
    assert "LoF defects" in evidence_item["quote"]


def test_with_presentation_axis_coverage_distinguishes_mechanism_from_missing():
    source_text = (
        "The present results indicate that the increasing VED leads to lower "
        "fraction of defects, slightly smaller defect size and complexity, "
        "and improves slightly the fatigue life."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-fatigue",
                    human_readable_id=3,
                    title="VED effects on defect structure and fatigue behaviour",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-fatigue-result",
                    document_id="paper-fatigue",
                    block_type="paragraph",
                    text=source_text,
                    block_order=139,
                    page=10,
                    heading_path="4.2. The influence of defect structure on fatigue strength",
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "empty",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-fatigue",
                "goal_id": "goal-fatigue",
                "title": (
                    "How do volumetric energy density, laser power, scanning "
                    "speed, hatch spacing, and layer thickness affect defect "
                    "structure and fatigue strength of 316L stainless steel "
                    "processed via laser beam powder bed fusion?"
                ),
            },
            "claims": [],
            "relations": [],
            "evidence_refs": [],
            "contexts": [],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    coverage = understanding["presentation"]["summary"]["axis_coverage"]
    assert {
        "axis": "defect structure",
        "status": "mechanism",
        "finding_id": "finding_claim_recovered_ved_defects_fatigue_blk-fatigue-result",
    } in coverage["properties"]
    assert {
        "axis": "fatigue strength",
        "status": "primary",
        "finding_id": "finding_claim_recovered_ved_defects_fatigue_blk-fatigue-result",
    } in coverage["properties"]
    assert all(
        "powder bed fusion" not in item["axis"].lower()
        for item in coverage["variables"]
    )
    assert {
        "axis": "volumetric energy density",
        "status": "primary",
        "finding_id": "finding_claim_recovered_ved_defects_fatigue_blk-fatigue-result",
    } in coverage["variables"]
    assert all(
        item["axis"] != "energy density" for item in coverage["variables"]
    )


def test_with_presentation_axis_coverage_treats_mechanical_properties_as_parent_axis():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-preheat",
                "goal_id": "goal-preheat",
                "title": (
                    "How does build platform preheating affect mechanical "
                    "properties of 316L stainless steel?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_ductility",
                    "claim_type": "finding",
                    "statement": (
                        "Build platform preheating to 150 °C increased ductility "
                        "by 14%."
                    ),
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_preheat_ductility"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat_ductility"],
                    "warnings": [],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_ductility",
                    "relation_type": "increases",
                    "subject": "build platform preheating temperature",
                    "predicate": "increases",
                    "object": "ductility",
                    "statement": (
                        "Build platform preheating to 150 °C increased ductility "
                        "by 14%."
                    ),
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_preheat_ductility"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_preheat_ductility"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_preheat_ductility",
                    "source_kind": "text_window",
                    "document_id": "paper-preheat",
                    "label": "P002 Conclusion",
                    "locator": {"source_ref": "blk-preheat-ductility", "page": 9},
                    "fact_ids": ["unit_preheat_ductility"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Preheating the build platform to 150 °C increased the "
                        "ductility of material by 14%."
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
                        ],
                    },
                    "property_scope": ["mechanical properties"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["primary_findings"][0]
    assert finding["outcomes"] == ["ductility"]
    coverage = understanding["presentation"]["summary"]["axis_coverage"]
    assert {
        "axis": "mechanical properties",
        "status": "primary",
        "finding_id": finding["finding_id"],
    } in coverage["properties"]


def test_with_presentation_axis_coverage_excludes_platform_process_from_variables():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-lpbf",
                    human_readable_id=6,
                    title="LPBF texture and yield strength",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-yield-validation",
                    document_id="paper-lpbf",
                    block_type="paragraph",
                    text=(
                        "The scan strategy rotation angle and build orientation "
                        "were used for yield strength prediction. The order is "
                        "predicted to remain 45-22.5-0 > 45-45-0 > 90-90-0 "
                        "> 67.5-67.5-0 > 0-0-0. The difference between the "
                        "simulation and the experimental data is less than 5%."
                    ),
                    block_order=89,
                    page=8,
                    heading_path="3.4. Yield strength prediction and validation",
                )
            ],
            tables=[
                SourceTable(
                    table_id="tbl-yield-validation",
                    document_id="paper-lpbf",
                    table_order=3,
                    caption_text=(
                        "Table 3 The prediction and average experimental yield "
                        "strength results of samples built in different scanning "
                        "strategies and building orientations."
                    ),
                    caption_block_id=None,
                    page=8,
                    bbox=None,
                    heading_path="3.4. Yield strength prediction and validation",
                    column_headers=(
                        "α (°)",
                        "β (°)",
                        "θ (°)",
                        "Yield Strength Prediction (MPa)",
                        "Yield Strength Experiment (MPa)",
                    ),
                    table_matrix=(
                        ("0", "0", "0", "310.48", "334.2"),
                        ("0", "0", "45", "328.67", "351.9"),
                        ("45", "22.5", "0", "341.85", "363.1"),
                    ),
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "empty",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-texture",
                "goal_id": "goal-texture",
                "title": (
                    "How do scan strategy rotation angle, build orientation "
                    "angle, and Laser Powder Bed Fusion affect crystallographic "
                    "texture and yield strength of 316L stainless steel?"
                ),
            },
            "claims": [],
            "relations": [],
            "evidence_refs": [],
            "contexts": [],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    coverage = understanding["presentation"]["summary"]["axis_coverage"]
    assert all(
        "powder bed fusion" not in item["axis"].lower()
        for item in coverage["variables"]
    )
    assert {
        "axis": "yield strength",
        "status": "review_queue",
        "finding_id": (
            "finding_claim_recovered_texture_yield_build_orientation_"
            "blk-yield-validation"
        ),
    } in coverage["properties"]


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
    assert understanding["presentation"]["summary"]["review_queue_count"] == 0


def test_with_presentation_promotes_single_paper_relation_with_aligned_direct_evidence():
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
                    "claim_id": "claim_porosity_corrosion",
                    "claim_type": "finding",
                    "statement": (
                        "Porosity level affects pitting corrosion behavior."
                    ),
                    "status": "supported",
                    "confidence": 0.88,
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
                        "Lower porosity increases pitting potential and improves "
                        "pitting corrosion behavior."
                    ),
                    "status": "supported",
                    "confidence": 0.88,
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
                    "label": "P005 Conclusion",
                    "locator": {"source_ref": "blk-corrosion"},
                    "fact_ids": ["unit_corrosion"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "The pitting potential gradually increases with the "
                        "decreased porosity. The passive film formed on the "
                        "surface of low porosity sample was more stable and "
                        "exhibited better corrosion properties."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["porosity level"]
                    },
                    "property_scope": ["pitting corrosion behavior"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["title"] == "porosity level -> pitting corrosion behavior"
    assert finding["mediators"] == ["passive film"]
    assert finding["evidence_bundle"]["mechanism"] == ["evref_corrosion"]
    assert finding["statement"] == (
        "Across the tested SLM conditions, lower-porosity samples were associated "
        "with higher pitting potential and a more stable passive film, consistent "
        "with better pitting-corrosion resistance. This paper-level evidence does "
        "not isolate porosity as a causal variable."
    )
    assert finding["direction"] == "associated"
    assert "paper_level_association" in finding["warnings"]
    assert "process_conditions_not_isolated" not in finding["review_reasons"]
    assert finding["support_grade"] == "partial"
    assert understanding["presentation"]["primary_findings"] == [finding]
    assert understanding["presentation"]["review_queue_findings"] == []


def test_with_presentation_does_not_merge_cross_paper_measurements_as_finding():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
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
                    "claim_id": "claim_density_low",
                    "claim_type": "comparison",
                    "statement": "Laser power and scan speed affect density.",
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_density_low"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density_low"],
                },
                {
                    "claim_id": "claim_density_high",
                    "claim_type": "comparison",
                    "statement": "Laser power and scan speed affect density.",
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_density_high"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density_high"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_density_low",
                    "relation_type": "affects",
                    "subject": "laser power and scan speed",
                    "predicate": "affects",
                    "object": "density",
                    "statement": "Laser power and scan speed affect density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density_low"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density_low"],
                },
                {
                    "relation_id": "rel_density_high",
                    "relation_type": "affects",
                    "subject": "laser power and scan speed",
                    "predicate": "affects",
                    "object": "density",
                    "statement": "Laser power and scan speed affect density.",
                    "status": "supported",
                    "evidence_ref_ids": ["evref_density_high"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_density_high"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_density_low",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-density-low"},
                    "fact_ids": ["unit_density_low"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "The achieved density measured using the Archimedes "
                        "method was 91.9% for L-VED."
                    ),
                },
                {
                    "evidence_ref_id": "evref_density_high",
                    "source_kind": "text_window",
                    "document_id": "paper-2",
                    "label": "P002 Results",
                    "locator": {"source_ref": "blk-density-high"},
                    "fact_ids": ["unit_density_high"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "The achieved density measured using the Archimedes "
                        "method was 99.6% for H-VED."
                    ),
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["laser power", "scan speed"]
                    },
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    assert understanding["presentation"]["findings"] == []
    assert understanding["presentation"]["primary_findings"] == []
    assert understanding["presentation"]["review_queue_findings"] == []
    assert {
        item["evidence_ref_id"]
        for item in understanding["presentation"]["evidence_items"]
    } == {"evref_density_low", "evref_density_high"}


def test_presentation_filters_multi_outcome_row_covered_by_specific_findings():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    evidence_by_id = {
        "evref_ductility": {"document_id": "paper-1"},
        "evref_mechanism": {"document_id": "paper-1"},
        "evref_yield": {"document_id": "paper-1"},
        "evref_uts": {"document_id": "paper-1"},
    }
    findings = [
        {
            "finding_id": "finding_recovered_ductility",
            "claim_id": "claim_recovered_preheating_ductility_blk-1",
            "variables": ["build platform preheating temperature"],
            "outcomes": ["ductility"],
            "support_grade": "partial",
            "evidence_ref_ids": ["evref_ductility"],
            "evidence_bundle": {"direct_result": ["evref_ductility"]},
            "relation_chain": [{"outcome": "ductility"}],
        },
        {
            "finding_id": "finding_mechanism",
            "claim_id": "claim_preheating_mechanism",
            "variables": ["build platform preheating"],
            "outcomes": ["ductility", "yield strength"],
            "support_grade": "partial",
            "evidence_ref_ids": ["evref_mechanism"],
            "evidence_bundle": {"direct_result": ["evref_mechanism"]},
            "relation_chain": [
                {"outcome": "ductility and yield strength"}
            ],
        },
        {
            "finding_id": "finding_yield",
            "claim_id": "relation_rel_yield",
            "variables": ["build platform preheating temperature"],
            "outcomes": ["yield strength"],
            "support_grade": "partial",
            "evidence_ref_ids": ["evref_yield"],
            "evidence_bundle": {"direct_result": ["evref_yield"]},
            "relation_chain": [{"outcome": "yield strength"}],
        },
        {
            "finding_id": "finding_uts",
            "claim_id": "relation_rel_uts",
            "variables": ["build platform preheating temperature"],
            "outcomes": ["ultimate tensile strength"],
            "support_grade": "partial",
            "evidence_ref_ids": ["evref_uts"],
            "evidence_bundle": {"direct_result": ["evref_uts"]},
            "relation_chain": [{"outcome": "ultimate tensile strength"}],
        },
    ]

    filtered = service._findings_without_redundant_multi_outcome_rows(
        findings,
        evidence_by_id=evidence_by_id,
    )

    assert [finding["finding_id"] for finding in filtered] == [
        "finding_recovered_ductility",
        "finding_yield",
        "finding_uts",
    ]


def test_presentation_keeps_coupled_parameter_set_finding_beside_single_axis_rows():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    evidence_by_id = {
        "evref-coupled": {"document_id": "paper-1"},
        "evref-yield": {"document_id": "paper-1"},
        "evref-uts": {"document_id": "paper-1"},
        "evref-elongation": {"document_id": "paper-1"},
    }
    coupled = {
        "finding_id": "finding-coupled",
        "variables": [
            "coupled SLM parameter sets: scanning strategy, scanning speed, "
            "hatch spacing, and energy density"
        ],
        "outcomes": [
            "yield strength",
            "ultimate tensile strength",
            "elongation",
        ],
        "support_grade": "partial",
        "evidence_ref_ids": ["evref-coupled"],
        "evidence_bundle": {"direct_result": ["evref-coupled"]},
        "relation_chain": [{"outcome": "mechanical properties"}],
        "warnings": ["single_variable_effect_not_isolated"],
    }
    single_axis_rows = [
        {
            "finding_id": f"finding-{outcome}",
            "variables": ["scanning strategy"],
            "outcomes": [outcome],
            "support_grade": "partial",
            "evidence_ref_ids": [evidence_ref_id],
            "evidence_bundle": {"direct_result": [evidence_ref_id]},
            "relation_chain": [{"outcome": outcome}],
        }
        for outcome, evidence_ref_id in (
            ("yield strength", "evref-yield"),
            ("ultimate tensile strength", "evref-uts"),
            ("elongation", "evref-elongation"),
        )
    ]

    filtered = service._findings_without_redundant_multi_outcome_rows(
        [coupled, *single_axis_rows],
        evidence_by_id=evidence_by_id,
    )

    assert [finding["finding_id"] for finding in filtered] == [
        "finding-coupled",
        "finding-yield strength",
        "finding-ultimate tensile strength",
        "finding-elongation",
    ]


def test_with_presentation_keeps_same_paper_comparable_finding_when_recovered_expert_finding_exists():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does VED affect fatigue strength?",
            },
            "claims": [
                {
                    "claim_id": "claim_recovered_ved_fatigue_blk-1",
                    "claim_type": "finding",
                    "statement": (
                        "Increasing VED reduces defect fraction and defect size, "
                        "which improves fatigue strength but does not eliminate "
                        "fatigue-limit loss from remaining LoF defects."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_recovered_ved_fatigue_blk-1"],
                    "context_ids": ["ctx_recovered"],
                    "source_object_ids": ["claim_recovered_ved_fatigue_blk-1"],
                },
                {
                    "claim_id": "claim_row_fatigue",
                    "claim_type": "comparison",
                    "statement": (
                        "Under layer thickness 30, VED increased fatigue strength "
                        "from 340 MPa to 450 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_table_fatigue"],
                    "context_ids": ["ctx_row"],
                    "source_object_ids": ["unit_row_fatigue"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_recovered_ved_fatigue_blk-1",
                    "relation_type": "improves",
                    "subject": "volumetric energy density",
                    "predicate": "reduces",
                    "object": "defect structure -> fatigue strength",
                    "statement": (
                        "Increasing VED reduces defect fraction and defect size, "
                        "which improves fatigue strength but does not eliminate "
                        "fatigue-limit loss from remaining LoF defects."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_recovered_ved_fatigue_blk-1"],
                    "context_ids": ["ctx_recovered"],
                    "source_object_ids": ["claim_recovered_ved_fatigue_blk-1"],
                },
                {
                    "relation_id": "rel_row_fatigue",
                    "relation_type": "increases",
                    "subject": "volumetric energy density",
                    "predicate": "increases",
                    "object": "fatigue strength",
                    "statement": (
                        "Under layer thickness 30, volumetric energy density "
                        "increased fatigue strength from 340 MPa to 450 MPa."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_table_fatigue"],
                    "context_ids": ["ctx_row"],
                    "source_object_ids": ["unit_row_fatigue"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_recovered_ved_fatigue_blk-1",
                    "source_kind": "paragraph",
                    "document_id": "paper-1",
                    "label": "4.2. The influence of defect structure on fatigue strength",
                    "locator": {"source_ref": "blk-1"},
                    "fact_ids": ["claim_recovered_ved_fatigue_blk-1"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "The present results indicate that the increasing VED "
                        "leads to lower fraction of defects, slightly smaller "
                        "defect size and improves slightly the fatigue life."
                    ),
                },
                {
                    "evidence_ref_id": "evref_table_fatigue",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "Table 5",
                    "locator": {"source_ref": "tbl-fatigue"},
                    "fact_ids": ["unit_row_fatigue"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_recovered",
                    "label": "Recovered source scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["volumetric energy density"]
                    },
                    "property_scope": ["defect structure", "fatigue strength"],
                },
                {
                    "context_id": "ctx_row",
                    "label": "Row scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["volumetric energy density"]
                    },
                    "property_scope": ["fatigue life"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    primary = understanding["presentation"]["primary_findings"]
    review = understanding["presentation"]["review_queue_findings"]
    assert [finding["claim_id"] for finding in primary] == [
        "claim_recovered_ved_fatigue_blk-1",
    ]
    row_finding = next(
        finding for finding in review if finding["claim_id"] == "claim_row_fatigue"
    )
    assert row_finding["title"] == "volumetric energy density -> fatigue strength"
    assert row_finding["variables"] == ["volumetric energy density"]
    assert primary[0]["related_review_finding_ids"] == [row_finding["finding_id"]]
    assert "has_unreviewed_comparable_candidates" in primary[0]["review_reasons"]


def test_with_presentation_hides_ved_table_row_when_recovered_finding_uses_same_table():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "title": "How does VED affect defect structure and fatigue strength?",
            },
            "claims": [
                {
                    "claim_id": "claim_recovered_ved_defects_fatigue_blk-1",
                    "claim_type": "finding",
                    "statement": (
                        "Increasing VED lowered defect fraction and increased "
                        "fatigue strength from 340 MPa to 450 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": [
                        "evref_recovered_ved_defects_fatigue_blk-1",
                        "evref_recovered_ved_defects_fatigue_table_tbl-fatigue",
                    ],
                    "context_ids": ["ctx_recovered"],
                    "source_object_ids": ["claim_recovered_ved_defects_fatigue_blk-1"],
                },
                {
                    "claim_id": "claim_row_fatigue",
                    "claim_type": "comparison",
                    "statement": (
                        "Under layer thickness 30, volumetric energy density "
                        "increased fatigue strength from 340 MPa to 450 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_table_fatigue"],
                    "context_ids": ["ctx_row"],
                    "source_object_ids": ["unit_row_fatigue"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_recovered_ved_defects_fatigue_blk-1",
                    "relation_type": "improves",
                    "subject": "volumetric energy density",
                    "predicate": "improves",
                    "object": "defect structure -> fatigue strength",
                    "statement": (
                        "Increasing VED lowered defect fraction and increased "
                        "fatigue strength from 340 MPa to 450 MPa."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": [
                        "evref_recovered_ved_defects_fatigue_blk-1",
                        "evref_recovered_ved_defects_fatigue_table_tbl-fatigue",
                    ],
                    "context_ids": ["ctx_recovered"],
                    "source_object_ids": ["claim_recovered_ved_defects_fatigue_blk-1"],
                },
                {
                    "relation_id": "rel_row_fatigue",
                    "relation_type": "increases",
                    "subject": "volumetric energy density",
                    "predicate": "increases",
                    "object": "fatigue strength",
                    "statement": (
                        "Under layer thickness 30, volumetric energy density "
                        "increased fatigue strength from 340 MPa to 450 MPa."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_table_fatigue"],
                    "context_ids": ["ctx_row"],
                    "source_object_ids": ["unit_row_fatigue"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_recovered_ved_defects_fatigue_blk-1",
                    "source_kind": "paragraph",
                    "document_id": "paper-1",
                    "label": "4.2. The influence of defect structure on fatigue strength",
                    "locator": {"source_ref": "blk-1"},
                    "fact_ids": ["claim_recovered_ved_defects_fatigue_blk-1"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "Increasing VED leads to lower fraction of defects.",
                },
                {
                    "evidence_ref_id": "evref_recovered_ved_defects_fatigue_table_tbl-fatigue",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "Table 5",
                    "locator": {"source_ref": "tbl-fatigue"},
                    "fact_ids": ["claim_recovered_ved_defects_fatigue_blk-1"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Table 5 FAT at 10 4 cycles L-VED 340 MPa "
                        "M-VED 450 MPa."
                    ),
                },
                {
                    "evidence_ref_id": "evref_table_fatigue",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "Table 5",
                    "locator": {"source_ref": "tbl-fatigue"},
                    "fact_ids": ["unit_row_fatigue"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Table 5 FAT at 10 4 cycles L-VED 340 MPa "
                        "M-VED 450 MPa."
                    ),
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_recovered",
                    "label": "Recovered source scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["volumetric energy density"]
                    },
                    "property_scope": ["defect structure", "fatigue strength"],
                },
                {
                    "context_id": "ctx_row",
                    "label": "Row scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["volumetric energy density"]
                    },
                    "property_scope": ["fatigue strength"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    assert [
        finding["claim_id"]
        for finding in understanding["presentation"]["primary_findings"]
    ] == ["claim_recovered_ved_defects_fatigue_blk-1"]
    assert not any(
        finding["claim_id"] == "claim_row_fatigue"
        for finding in understanding["presentation"]["review_queue_findings"]
    )


def test_with_presentation_keeps_numeric_row_direct_evidence_when_recovered_source_exists():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-1",
                    human_readable_id=1,
                    title="Heat treatment density study",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-row-density",
                    document_id="paper-1",
                    block_type="table",
                    text=(
                        "Under laser power 140 and scan speed 100, Furnace HT "
                        "increased density from 98.16 % to 98.33 %."
                    ),
                    block_order=20,
                    page=4,
                    heading_path="Table 2",
                ),
                SourceBlock(
                    block_id="blk-recovered-conclusion",
                    document_id="paper-1",
                    block_type="list_item",
                    text=(
                        "Mechanical properties: heat treatments reduced "
                        "dislocation density and changed tensile strength."
                    ),
                    block_order=134,
                    page=12,
                    heading_path="4. Conclusion",
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
                "title": "How does heat treatment affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_row_density",
                    "claim_type": "comparison",
                    "statement": (
                        "Under laser power 140 and scan speed 100, heat "
                        "treatment type Furnace HT increased density from "
                        "98.16 % to 98.33 %."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_row_density"],
                    "context_ids": ["ctx_row"],
                    "source_object_ids": ["unit_row_density"],
                },
                {
                    "claim_id": "claim_recovered_heat_blk-recovered-conclusion",
                    "claim_type": "finding",
                    "statement": (
                        "Heat treatment changed microstructure and mechanical "
                        "properties."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_recovered_heat_blk-recovered-conclusion"],
                    "context_ids": ["ctx_recovered"],
                    "source_object_ids": ["claim_recovered_heat_blk-recovered-conclusion"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_row_density",
                    "relation_type": "increases",
                    "subject": "heat treatment",
                    "predicate": "increases",
                    "object": "density",
                    "statement": (
                        "Under laser power 140 and scan speed 100, heat "
                        "treatment type Furnace HT increased density from "
                        "98.16 % to 98.33 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_row_density"],
                    "context_ids": ["ctx_row"],
                    "source_object_ids": ["unit_row_density"],
                },
                {
                    "relation_id": "rel_recovered_heat_blk-recovered-conclusion",
                    "relation_type": "changes",
                    "subject": "heat treatment",
                    "predicate": "changes",
                    "object": "microstructure",
                    "statement": (
                        "Heat treatment changed microstructure and mechanical "
                        "properties."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_recovered_heat_blk-recovered-conclusion"],
                    "context_ids": ["ctx_recovered"],
                    "source_object_ids": ["claim_recovered_heat_blk-recovered-conclusion"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_row_density",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "Table 2 density row",
                    "locator": {"source_ref": "blk-row-density"},
                    "fact_ids": ["unit_row_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Under laser power 140 and scan speed 100, Furnace HT "
                        "increased density from 98.16 % to 98.33 %."
                    ),
                },
                {
                    "evidence_ref_id": "evref_recovered_heat_blk-recovered-conclusion",
                    "source_kind": "list_item",
                    "document_id": "paper-1",
                    "label": "4. Conclusion",
                    "locator": {"source_ref": "blk-recovered-conclusion"},
                    "fact_ids": ["claim_recovered_heat_blk-recovered-conclusion"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Mechanical properties: heat treatments reduced "
                        "dislocation density and changed tensile strength."
                    ),
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_row",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["heat treatment"]},
                    "property_scope": ["density"],
                },
                {
                    "context_id": "ctx_recovered",
                    "label": "Recovered source scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["heat treatment"]},
                    "property_scope": ["microstructure"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    assert not any(
        finding["claim_id"] == "claim_row_density"
        for finding in understanding["presentation"]["findings"]
    )
    assert not any(
        finding["claim_id"] == "claim_row_density"
        for finding in understanding["presentation"]["review_queue_findings"]
    )


def test_with_presentation_keeps_table_row_evidence_out_of_primary_when_discussion_exists():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-1",
                    human_readable_id=1,
                    title="SLM process density study",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-discussion",
                    document_id="paper-1",
                    block_type="paragraph",
                    text=(
                        "The pores with irregular shapes were observed in SLM "
                        "samples built at laser power 140 W and scan speed "
                        "100 mm/s, and density improved when porosity decreased."
                    ),
                    block_order=75,
                    page=8,
                    heading_path="3. Results and discussion",
                )
            ],
            tables=[
                SourceTable(
                    table_id="tbl-density",
                    document_id="paper-1",
                    table_order=2,
                    caption_text="Table 2. Density of SLM samples.",
                    caption_block_id=None,
                    page=5,
                    bbox=None,
                    heading_path="3. Results and discussion",
                    column_headers=("laser power", "scan speed", "density"),
                    table_matrix=(
                        ("120 W", "100 mm/s", "98.45 %"),
                        ("140 W", "100 mm/s", "98.33 %"),
                    ),
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
                "title": "How does laser power affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_row_density",
                    "claim_type": "comparison",
                    "statement": (
                        "Under scan speed 100, laser power 140 decreased "
                        "density from 98.45 % (laser power 120) to 98.33 %."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_row_density"],
                    "context_ids": ["ctx_row"],
                    "source_object_ids": ["unit_row_density"],
                },
                {
                    "claim_id": "claim_density_discussion",
                    "claim_type": "finding",
                    "statement": (
                        "Increasing laser power and scan speed changed "
                        "density through porosity evolution."
                    ),
                    "status": "supported",
                    "confidence": 0.84,
                    "evidence_ref_ids": ["evref_discussion"],
                    "context_ids": ["ctx_row"],
                    "source_object_ids": ["unit_discussion"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_row_density",
                    "relation_type": "decreases",
                    "subject": "laser power",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "Under scan speed 100, laser power 140 decreased "
                        "density from 98.45 % (laser power 120) to 98.33 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_row_density"],
                    "context_ids": ["ctx_row"],
                    "source_object_ids": ["unit_row_density"],
                },
                {
                    "relation_id": "rel_density_discussion",
                    "relation_type": "decreases",
                    "subject": "laser power",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "Increasing laser power and scan speed changed "
                        "density through porosity evolution."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_discussion"],
                    "context_ids": ["ctx_row"],
                    "source_object_ids": ["unit_discussion"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_row_density",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_row_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
                {
                    "evidence_ref_id": "evref_discussion",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "Results discussion",
                    "locator": {"source_ref": "blk-discussion"},
                    "fact_ids": ["unit_discussion"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "The pores with irregular shapes were observed in SLM "
                        "samples built at laser power 140 W and scan speed "
                        "100 mm/s, and density improved when porosity decreased."
                    ),
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_row",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["laser power"]},
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    row_finding = next(
        finding
        for finding in understanding["presentation"]["findings"]
        if finding["claim_id"] == "claim_row_density"
    )
    assert row_finding["evidence_bundle"]["direct_result"] == ["evref_row_density"]
    assert "evref_discussion" in row_finding["evidence_bundle"]["uncategorized"]
    assert not any(
        finding["claim_id"] == "claim_row_density"
        for finding in understanding["presentation"]["primary_findings"]
    )
    assert any(
        finding["claim_id"] == "claim_row_density"
        for finding in understanding["presentation"]["review_queue_findings"]
    )


def test_with_presentation_filters_low_delta_table_axis_when_stronger_axis_exists():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-density",
                    human_readable_id=4,
                    title="Heat treatment and process density study",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-heat-treatment",
                    document_id="paper-density",
                    block_type="paragraph",
                    text=(
                        "A relatively higher density was obtained by increasing "
                        "the applied laser energy density. Microstructure: heat "
                        "treatments increased density and "
                        "removed cellular microstructure and dense dislocation "
                        "structures owing to recrystallization."
                    ),
                    block_order=133,
                    page=12,
                    heading_path="4. Conclusions",
                )
            ],
            tables=[
                SourceTable(
                    table_id="tbl-density",
                    document_id="paper-density",
                    table_order=2,
                    caption_text="Table 2. Relative density of SLM samples.",
                    caption_block_id=None,
                    page=6,
                    bbox=None,
                    heading_path="3. Results and discussion",
                    column_headers=(
                        "laser power",
                        "scan speed",
                        "heat treatment type",
                        "density",
                    ),
                    table_matrix=(
                        ("100 W", "200 mm/s", "Furnace HT", "93.67 %"),
                        ("120 W", "200 mm/s", "Furnace HT", "96.84 %"),
                        ("140 W", "100 mm/s", "Furnace HT", "98.33 %"),
                        ("140 W", "200 mm/s", "Furnace HT", "97.06 %"),
                    ),
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": (
                    "How do heat treatment, laser power, and scan speed affect "
                    "density and microstructure of stainless steel 316L?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_heat_treatment",
                    "claim_type": "finding",
                    "statement": (
                        "Heat treatments increased density and removed cellular "
                        "microstructure and dense dislocation structures."
                    ),
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_heat_treatment"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_heat_treatment"],
                },
                {
                    "claim_id": "claim_laser_density",
                    "claim_type": "comparison",
                    "statement": (
                        "Under heat treatment type furnace ht and scan speed 200, "
                        "laser power 120 increased density from 93.67 % "
                        "(laser power 100) to 96.84 %."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_laser_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_laser_density"],
                    "warnings": ["deterministic_relation"],
                },
                {
                    "claim_id": "claim_laser_density_high_speed",
                    "claim_type": "comparison",
                    "statement": (
                        "Under heat treatment type furnace ht and scan speed 100, "
                        "laser power 140 decreased density from 98.45 % "
                        "(laser power 120) to 98.33 %."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_laser_density_high_speed"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_laser_density_high_speed"],
                    "warnings": ["deterministic_relation"],
                },
                {
                    "claim_id": "claim_scan_density",
                    "claim_type": "comparison",
                    "statement": (
                        "Under heat treatment type furnace ht and laser power 140, "
                        "scan speed 200 decreased density from 98.33 % "
                        "(scan speed 100) to 97.06 %."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_scan_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_scan_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_heat_treatment",
                    "relation_type": "affects",
                    "subject": "heat treatment",
                    "predicate": "affects",
                    "object": "density and microstructure",
                    "statement": (
                        "Heat treatments increased density and removed cellular "
                        "microstructure and dense dislocation structures."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_heat_treatment"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_heat_treatment"],
                },
                {
                    "relation_id": "rel_laser_density",
                    "relation_type": "increases",
                    "subject": "laser power",
                    "predicate": "increases",
                    "object": "density",
                    "statement": (
                        "Under heat treatment type furnace ht and scan speed 200, "
                        "laser power 120 increased density from 93.67 % "
                        "(laser power 100) to 96.84 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_laser_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_laser_density"],
                },
                {
                    "relation_id": "rel_laser_density_high_speed",
                    "relation_type": "decreases",
                    "subject": "laser power",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "Under heat treatment type furnace ht and scan speed 100, "
                        "laser power 140 decreased density from 98.45 % "
                        "(laser power 120) to 98.33 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_laser_density_high_speed"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_laser_density_high_speed"],
                },
                {
                    "relation_id": "rel_scan_density",
                    "relation_type": "decreases",
                    "subject": "scan speed",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "Under heat treatment type furnace ht and laser power 140, "
                        "scan speed 200 decreased density from 98.33 % "
                        "(scan speed 100) to 97.06 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_scan_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_scan_density"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_heat_treatment",
                    "source_kind": "text_window",
                    "document_id": "paper-density",
                    "label": "P004 Conclusions",
                    "locator": {"source_ref": "blk-heat-treatment"},
                    "fact_ids": ["unit_heat_treatment"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "A relatively higher density was obtained by increasing "
                        "the applied laser energy density. Microstructure: heat "
                        "treatments increased density and "
                        "removed cellular microstructure and dense dislocation "
                        "structures owing to recrystallization."
                    ),
                },
                {
                    "evidence_ref_id": "evref_laser_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_laser_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
                {
                    "evidence_ref_id": "evref_laser_density_high_speed",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_laser_density_high_speed"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
                {
                    "evidence_ref_id": "evref_scan_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_scan_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "variable_process_axes": [
                            "heat treatment",
                            "laser power",
                            "scan speed",
                        ],
                    },
                    "property_scope": ["density", "microstructure"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    primary_titles = [
        finding["title"]
        for finding in understanding["presentation"]["primary_findings"]
    ]
    assert primary_titles == ["heat treatment -> density and microstructure"]
    assert all(
        finding["generalization_status"] == "paper_level_only"
        for finding in understanding["presentation"]["primary_findings"]
    )
    review_queue_titles = [
        finding["title"]
        for finding in understanding["presentation"]["review_queue_findings"]
    ]
    assert "laser power -> density" in review_queue_titles
    assert "scan speed -> density" not in review_queue_titles
    review_by_title = {
        finding["title"]: finding
        for finding in understanding["presentation"]["review_queue_findings"]
    }
    assert review_by_title["laser power -> density"]["statement"] == (
        "Selected source table rows show: "
        "Under heat treatment type furnace ht and scan speed 200, "
        "laser power 120 increased density from 93.67 % "
        "(laser power 100) to 96.84 %. "
        "Expert review is required before treating this as a material effect."
    )
    assert review_by_title["laser power -> density"]["comparison_summary"] == {
        "variable": "laser power",
        "direction": "condition-dependent",
        "outcome": "density",
        "baseline": {
            "label": "laser power 100",
            "value": "93.67 %",
        },
        "observed": {
            "label": "laser power 120",
            "value": "96.84 %",
        },
        "controlled_conditions": [
            {"axis": "heat treatment type", "value": "furnace ht"},
            {"axis": "scan speed", "value": "200"},
        ],
    }
    assert review_by_title["laser power -> density"]["direction"] == (
        "condition-dependent"
    )
    assert review_by_title["laser power -> density"]["relation_chain"] == [
        {
            **review_by_title["laser power -> density"]["relation_chain"][0],
            "direction": "condition-dependent",
            "statement": review_by_title["laser power -> density"]["statement"],
        }
    ]


def test_table_row_review_candidate_syncs_projected_relation_semantics():
    service = ResearchUnderstandingService()
    statement = (
        "Under energy density 150, scanning strategy A increased elongation "
        "from 4.29 % (scanning strategy B) to 41.9 %."
    )
    finding = {
        "title": "scanning strategy -> elongation",
        "statement": statement,
        "variables": ["scanning strategy"],
        "mediators": [],
        "outcomes": ["elongation"],
        "direction": "increases",
        "comparison_summary": {
            "variable": "scanning strategy",
            "direction": "increases",
            "outcome": "elongation",
            "baseline": {
                "label": "scanning strategy B",
                "value": "4.29 %",
            },
            "observed": {
                "label": "scanning strategy A",
                "value": "41.9 %",
            },
            "controlled_conditions": [
                {"axis": "energy density", "value": "150"},
            ],
        },
        "relation_chain": [
            {
                "relation_id": "rel_strategy_elongation",
                "variable": "scanning strategy",
                "mediators": [],
                "outcome": "elongation",
                "direction": "increases",
                "statement": statement,
            }
        ],
        "support_grade": "partial",
        "review_status": "needs_review",
        "paper_count": 1,
        "evidence_bundle": {"direct_result": ["evref_strategy_elongation"]},
        "review_reasons": [],
    }

    updated = service._finding_as_review_candidate(
        finding,
        reason="table_row_needs_expert_review",
    )

    expected_statement = (
        f"Selected source table rows show: {statement} "
        "Expert review is required before treating this as a material effect."
    )
    assert updated["statement"] == expected_statement
    assert updated["direction"] == "condition-dependent"
    assert updated["comparison_summary"]["direction"] == "condition-dependent"
    assert updated["relation_chain"] == [
        {
            "relation_id": "rel_strategy_elongation",
            "variable": "scanning strategy",
            "mediators": [],
            "outcome": "elongation",
            "direction": "condition-dependent",
            "statement": expected_statement,
        }
    ]


def test_with_presentation_uses_representative_table_axis_delta_for_filtering():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": (
                    "How do laser power and scan speed affect density of "
                    "stainless steel 316L?"
                ),
            },
            "claims": [],
            "relations": [
                {
                    "relation_id": "rel_laser_density_small",
                    "relation_type": "decreases",
                    "subject": "laser power",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "With scan speed 100 and heat treatment type Furnace HT, "
                        "changing laser power from 100 to 120 decreased density "
                        "from 98.70 % to 98.45 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_laser_density_small"],
                    "warnings": ["deterministic_relation"],
                },
                {
                    "relation_id": "rel_laser_density_large",
                    "relation_type": "increases",
                    "subject": "laser power",
                    "predicate": "increases",
                    "object": "density",
                    "statement": (
                        "With scan speed 200 and heat treatment type Furnace HT, "
                        "changing laser power from 100 to 120 increased density "
                        "from 93.67 % to 96.84 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_laser_density_large"],
                    "warnings": ["deterministic_relation"],
                },
                {
                    "relation_id": "rel_scan_density",
                    "relation_type": "decreases",
                    "subject": "scan speed",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "With laser power 100 and heat treatment type Furnace HT, "
                        "changing scan speed from 100 to 200 decreased density "
                        "from 98.70 % to 93.67 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_table"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_scan_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_table",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": [
                        "unit_laser_density_small",
                        "unit_laser_density_large",
                        "unit_scan_density",
                    ],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "variable_process_axes": ["laser power", "scan speed"],
                    },
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    review_by_title = {
        finding["title"]: finding
        for finding in understanding["presentation"]["review_queue_findings"]
    }
    assert "laser power -> density" not in review_by_title
    assert review_by_title["scan speed -> density"]["statement"] == (
        "Selected source table rows show: "
        "With laser power 100 and heat treatment type Furnace HT, "
        "changing scan speed from 100 to 200 decreased density "
        "from 98.70 % to 93.67 %. "
        "Expert review is required before treating this as a material effect."
    )


def test_with_presentation_keeps_representative_table_axis_provenance():
    service = ResearchUnderstandingService()
    small_statement = (
        "Under scan speed 100 and heat treatment type Furnace HT, laser power 120 "
        "decreased density from 98.70 % (laser power 100) to 98.45 %."
    )
    large_statement = (
        "Under scan speed 200 and heat treatment type Furnace HT, laser power 120 "
        "increased density from 90.00 % (laser power 100) to 98.00 %."
    )
    findings = [
        {
            "finding_id": "finding_relation_rel_small_delta",
            "claim_id": "relation_rel_small_delta",
            "title": "laser power -> density",
            "statement": small_statement,
            "variables": ["laser power"],
            "mediators": [],
            "outcomes": ["density"],
            "direction": "decreases",
            "relation_chain": [
                {
                    "relation_id": "rel_small_delta",
                    "variable": "laser power",
                    "mediators": [],
                    "outcome": "density",
                    "direction": "decreases",
                    "statement": small_statement,
                }
            ],
            "scope_summary": "stainless steel 316L",
            "support_grade": "partial",
            "review_status": "needs_review",
            "confidence": 0.62,
            "paper_count": 1,
            "evidence_count": 1,
            "evidence_ref_ids": ["evref_small_delta"],
            "context_ids": ["ctx_small_delta"],
            "relation_ids": ["rel_small_delta"],
            "evidence_bundle": {"direct_result": ["evref_small_delta"]},
            "warnings": ["deterministic_relation"],
        },
        {
            "finding_id": "finding_relation_rel_large_delta",
            "claim_id": "relation_rel_large_delta",
            "title": "laser power -> density",
            "statement": large_statement,
            "variables": ["laser power"],
            "mediators": [],
            "outcomes": ["density"],
            "direction": "increases",
            "relation_chain": [
                {
                    "relation_id": "rel_large_delta",
                    "variable": "laser power",
                    "mediators": [],
                    "outcome": "density",
                    "direction": "increases",
                    "statement": large_statement,
                }
            ],
            "scope_summary": "stainless steel 316L",
            "support_grade": "partial",
            "review_status": "needs_review",
            "confidence": 0.62,
            "paper_count": 1,
            "evidence_count": 1,
            "evidence_ref_ids": ["evref_large_delta"],
            "context_ids": ["ctx_large_delta"],
            "relation_ids": ["rel_large_delta"],
            "evidence_bundle": {"direct_result": ["evref_large_delta"]},
            "warnings": ["deterministic_relation"],
        },
    ]
    evidence_by_id = {
        "evref_small_delta": {
            "document_id": "paper-density",
            "locator": {"source_ref": "tbl-density"},
        },
        "evref_large_delta": {
            "document_id": "paper-density",
            "locator": {"source_ref": "tbl-density"},
        },
    }

    finding = service._merge_duplicate_presentation_findings(
        findings,
        evidence_by_id=evidence_by_id,
    )[0]

    assert "scan speed 200" in finding["statement"]
    assert finding["finding_id"] == "finding_relation_rel_large_delta"
    assert finding["claim_id"] == "relation_rel_large_delta"
    assert finding["relation_ids"] == ["rel_large_delta"]
    assert finding["context_ids"] == ["ctx_large_delta"]
    assert finding["evidence_ref_ids"] == ["evref_large_delta"]
    assert finding["evidence_bundle"]["direct_result"] == ["evref_large_delta"]
    assert [item["relation_id"] for item in finding["relation_chain"]] == [
        "rel_large_delta"
    ]


def test_low_magnitude_filter_reads_preheating_strength_delta_from_source_table():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    table = SourceTable(
        table_id="tbl-mechanical",
        document_id="paper-1",
        table_order=2,
        caption_text="Monotonic tensile properties under build platform conditions.",
        caption_block_id=None,
        page=8,
        bbox=None,
        heading_path="Results",
        column_headers=(
            "Build platform conditions",
            "ı y (MPa)",
            "ı u (MPa)",
            "El%",
        ),
        table_matrix=(
            ("Non-preheated", "448", "617", "72"),
            ("Preheated", "465", "618", "82"),
            ("Wrought", "255-310", "535-623", "30-40"),
        ),
    )
    evidence_by_id = {
        "evref_uts": {
            "evidence_ref_id": "evref_uts",
            "source_kind": "table",
            "document_id": "paper-1",
            "locator": {"source_ref": "tbl-mechanical"},
        },
        "evref_elongation": {
            "evidence_ref_id": "evref_elongation",
            "source_kind": "table",
            "document_id": "paper-1",
            "locator": {"source_ref": "tbl-mechanical"},
        },
    }
    review_queue = [
        {
            "finding_id": "finding_uts",
            "title": "build platform preheating temperature -> ultimate tensile strength",
            "statement": (
                "Increasing the build platform preheating temperature increases "
                "ultimate tensile strength."
            ),
            "variables": ["build platform preheating temperature"],
            "outcomes": ["ultimate tensile strength"],
            "evidence_bundle": {"direct_result": ["evref_uts"]},
            "relation_chain": [],
        },
        {
            "finding_id": "finding_elongation",
            "title": "build platform preheating temperature -> elongation",
            "statement": (
                "Increasing the build platform preheating temperature increases "
                "elongation."
            ),
            "variables": ["build platform preheating temperature"],
            "outcomes": ["elongation"],
            "evidence_bundle": {"direct_result": ["evref_elongation"]},
            "relation_chain": [],
        },
    ]

    projected_elongation = service._finding_with_preheating_table_comparison(
        review_queue[1],
        evidence_by_id=evidence_by_id,
        tables_by_id={table.table_id: table},
    )

    assert projected_elongation["statement"] == (
        "The source table reports elongation of 72% for the non-preheated "
        "condition and 82% for the preheated condition."
    )
    assert projected_elongation["comparison_summary"] == {
        "variable": "build platform preheating temperature",
        "direction": "increases",
        "outcome": "elongation",
        "baseline": {"label": "non-preheated", "value": "72%"},
        "observed": {"label": "preheated", "value": "82%"},
        "controlled_conditions": [],
    }

    filtered = service._review_findings_without_low_magnitude_table_rows(
        [review_queue[0], projected_elongation],
        evidence_by_id=evidence_by_id,
        tables_by_id={table.table_id: table},
    )

    assert [finding["finding_id"] for finding in filtered] == [
        "finding_elongation"
    ]


def test_with_presentation_keeps_distinct_table_review_comparisons_separate():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": "How does scan speed affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_scan_density_a",
                    "claim_type": "comparison",
                    "statement": (
                        "With laser power 100 and heat treatment type Furnace HT, "
                        "changing scan speed from 100 to 200 decreased density "
                        "from 98.70 % to 93.67 %."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_scan_density_a"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_scan_density_a"],
                    "warnings": ["deterministic_relation"],
                },
                {
                    "claim_id": "claim_scan_density_b",
                    "claim_type": "comparison",
                    "statement": (
                        "With laser power 100 and heat treatment type -, "
                        "changing scan speed from 100 to 200 decreased density "
                        "from 97.83 % to 91.84 %."
                    ),
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": ["evref_scan_density_b"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_scan_density_b"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_scan_density_a",
                    "relation_type": "decreases",
                    "subject": "scan speed",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "With laser power 100 and heat treatment type Furnace HT, "
                        "changing scan speed from 100 to 200 decreased density "
                        "from 98.70 % to 93.67 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_scan_density_a"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_scan_density_a"],
                },
                {
                    "relation_id": "rel_scan_density_b",
                    "relation_type": "decreases",
                    "subject": "scan speed",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "With laser power 100 and heat treatment type -, "
                        "changing scan speed from 100 to 200 decreased density "
                        "from 97.83 % to 91.84 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_scan_density_b"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_scan_density_b"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_scan_density_a",
                    "source_kind": "table",
                    "document_id": "paper-density-a",
                    "label": "P001 Table 2",
                    "locator": {"source_ref": "tbl-density-a"},
                    "fact_ids": ["unit_scan_density_a"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
                {
                    "evidence_ref_id": "evref_scan_density_b",
                    "source_kind": "table",
                    "document_id": "paper-density-b",
                    "label": "P002 Table 1",
                    "locator": {"source_ref": "tbl-density-b"},
                    "fact_ids": ["unit_scan_density_b"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {"variable_process_axes": ["scan speed"]},
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    review_scan_density = [
        finding
        for finding in understanding["presentation"]["review_queue_findings"]
        if finding["title"] == "scan speed -> density"
    ]
    assert len(review_scan_density) == 2
    assert {
        tuple(finding["evidence_bundle"]["direct_result"])
        for finding in review_scan_density
    } == {("evref_scan_density_a",), ("evref_scan_density_b",)}
    assert all(
        finding["statement"].startswith("Selected source table rows show:")
        for finding in review_scan_density
    )
    assert all(
        "changing scan speed from 100 to 200 decreased density" in finding["statement"]
        for finding in review_scan_density
    )
    assert all(
        "Expert review is required before treating this as a material effect."
        in finding["statement"]
        for finding in review_scan_density
    )


def test_with_presentation_keeps_derived_energy_density_out_of_variable_axes():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            tables=[
                SourceTable(
                    table_id="tbl-density",
                    document_id="paper-density",
                    table_order=2,
                    caption_text="Process conditions and relative density.",
                    caption_block_id=None,
                    page=4,
                    bbox=None,
                    heading_path="Results",
                    column_headers=(
                        "Laser power (W)",
                        "Scan speed (mm/s)",
                        "Laser energy density (J/mm3)",
                        "Heat treatment type",
                        "Density (%)",
                    ),
                    table_matrix=(
                        ("100", "100", "278", "-", "97.83"),
                        ("100", "200", "139", "-", "91.84"),
                        ("100", "200", "150", "-", "92.63"),
                        ("100", "200", "139", "HIP", "92.63"),
                        ("120", "200", "167", "HIP", "95.92"),
                    ),
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": "How do laser power and scan speed affect density?",
            },
            "claims": [],
            "relations": [
                {
                    "relation_id": "rel_scan_density",
                    "relation_type": "decreases",
                    "subject": "scan speed",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "Under laser power 100, scan speed 200 decreased density "
                        "from 97.83 % (scan speed 100) to 91.84 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_scan_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_scan_density"],
                    "warnings": ["deterministic_relation"],
                },
                {
                    "relation_id": "rel_power_density",
                    "relation_type": "increases",
                    "subject": "laser power",
                    "predicate": "increases",
                    "object": "density",
                    "statement": (
                        "Under heat treatment type HIP and scan speed 200, laser "
                        "power 120 increased density from 92.63 % (laser power "
                        "100) to 95.92 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_power_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_power_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_scan_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P001 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_scan_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
                {
                    "evidence_ref_id": "evref_power_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P001 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_power_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "variable_process_axes": ["laser power", "scan speed"],
                    },
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    review_by_title = {
        finding["title"]: finding
        for finding in understanding["presentation"]["review_queue_findings"]
    }
    assert set(review_by_title) == {
        "laser power -> density",
        "scan speed -> density",
    }
    scan_finding = review_by_title["scan speed -> density"]
    assert scan_finding["variables"] == ["scan speed"]
    assert scan_finding["direction"] == "condition-dependent"
    expected_scan_statement = (
        "Selected source table rows show: "
        "under laser power 100, scan speed changed from 100 mm/s to 200 mm/s "
        "while the derived energy density changed from 278 J/mm3 to 139 J/mm3; "
        "density changed from 97.83 % to 91.84 %. This is a condition-specific "
        "table association; the rows do not isolate a causal mechanism."
    )
    assert scan_finding["statement"] == expected_scan_statement
    assert scan_finding["relation_chain"] == [
        {
            "relation_id": "rel_scan_density",
            "variable": "scan speed",
            "mediators": [],
            "outcome": "density",
            "direction": "condition-dependent",
            "statement": expected_scan_statement,
        }
    ]
    assert scan_finding["comparison_summary"] == {
        "variable": "scan speed",
        "direction": "condition-dependent",
        "outcome": "density",
        "baseline": {
            "label": "scan speed 100 mm/s; derived energy density 278 J/mm3",
            "value": "97.83 %",
        },
        "observed": {
            "label": "scan speed 200 mm/s; derived energy density 139 J/mm3",
            "value": "91.84 %",
        },
        "controlled_conditions": [{"axis": "laser power", "value": "100"}],
    }
    assert "derived_energy_density_context" in scan_finding["review_reasons"]
    assert "single_variable_effect_not_isolated" not in scan_finding["review_reasons"]
    power_finding = review_by_title["laser power -> density"]
    assert power_finding["variables"] == ["laser power"]
    assert power_finding["direction"] == "condition-dependent"
    assert "laser power changed from 100 W to 120 W" in power_finding["statement"]
    assert (
        "derived energy density changed from 139 J/mm3 to 167 J/mm3"
        in power_finding["statement"]
    )
    assert "derived_energy_density_context" in power_finding["review_reasons"]
    assert "single_variable_effect_not_isolated" not in power_finding[
        "review_reasons"
    ]


def test_energy_density_context_preserves_independently_changed_hatch_spacing():
    service = ResearchUnderstandingService()
    finding = {
        "title": "scan speed -> density",
        "statement": (
            "Under laser power 100, scan speed 200 decreased density from "
            "97.83 % (scan speed 100) to 91.84 %."
        ),
        "variables": ["scan speed"],
        "outcomes": ["density"],
        "direction": "decreases",
        "comparison_summary": {
            "variable": "scan speed",
            "direction": "decreases",
            "outcome": "density",
            "baseline": {"label": "scan speed 100", "value": "97.83 %"},
            "observed": {"label": "scan speed 200", "value": "91.84 %"},
            "controlled_conditions": [{"axis": "laser power", "value": "100"}],
        },
        "evidence_bundle": {"direct_result": ["evref_scan_density"]},
        "review_reasons": ["table_row_needs_expert_review"],
        "warnings": ["deterministic_relation"],
        "relation_chain": [],
    }
    evidence_by_id = {
        "evref_scan_density": {
            "source_kind": "table",
            "locator": {"source_ref": "tbl-density"},
        }
    }
    tables_by_id = {
        "tbl-density": SourceTable(
            table_id="tbl-density",
            document_id="paper-density",
            table_order=2,
            caption_text="Process conditions and relative density.",
            caption_block_id=None,
            page=4,
            bbox=None,
            heading_path="Results",
            column_headers=(
                "Laser power (W)",
                "Scan speed (mm/s)",
                "Hatch spacing (mm)",
                "Laser energy density (J/mm3)",
                "Density (%)",
            ),
            table_matrix=(
                ("100", "100", "0.12", "278", "97.83"),
                ("100", "200", "0.10", "167", "91.84"),
            ),
        )
    }

    updated = service._finding_with_energy_density_context(
        finding,
        evidence_by_id=evidence_by_id,
        tables_by_id=tables_by_id,
    )

    assert updated["title"] == "scan speed + hatch spacing -> density"
    assert updated["variables"] == ["scan speed", "hatch spacing"]
    assert "hatch spacing changed from 0.12 mm to 0.10 mm" in updated["statement"]
    assert "the derived energy density changed from 278 J/mm3 to 167 J/mm3" in (
        updated["statement"]
    )
    assert "non_single_variable_table_comparison" in updated["review_reasons"]
    assert "single_variable_effect_not_isolated" in updated["review_reasons"]


def test_with_presentation_filters_multi_axis_table_row_comparison_from_findings():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": "How does scan speed affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_heat_density_small_delta",
                    "claim_type": "comparison",
                    "statement": (
                        "With laser power 100 and scan speed 200, changing "
                        "heat treatment type from HIP to Furnace HT increased "
                        "density from 92.63 % to 93.67 %."
                    ),
                    "status": "supported",
                    "confidence": 0.62,
                    "evidence_ref_ids": ["evref_heat_density"],
                    "context_ids": ["ctx_heat_density"],
                    "source_object_ids": ["unit_heat_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_scan_density_confounded",
                    "relation_type": "decreases",
                    "subject": "scan speed",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "Under energy density 150 and scanning strategy A, "
                        "scan speed 0.12 decreased density from 99.45 "
                        "(scan speed 0.111) to 97.14."
                    ),
                    "status": "supported",
                    "confidence": 0.62,
                    "evidence_ref_ids": ["evref_scan_density"],
                    "context_ids": ["ctx_scan_density"],
                    "source_object_ids": ["unit_scan_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_scan_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P001 Table 1",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_scan_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {"variable_process_axes": ["scan speed"]},
                    "property_scope": ["density"],
                },
                {
                    "context_id": "ctx_scan_density",
                    "label": "Claim applicability",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "baseline_context": {
                            "process_context": {
                                "Hatch space (mm)": "0.12",
                                "Scan strategy": "A",
                                "Scanning speed (mm/s)": "0.111",
                            },
                            "source_value_text": "99.45",
                            "value": 99.45,
                        },
                        "process_context": {
                            "Hatch space (mm)": "0.111",
                            "Scan strategy": "A",
                            "Scanning speed (mm/s)": "0.12",
                        },
                    },
                    "property_scope": ["density"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    presentation = understanding["presentation"]
    assert presentation["findings"] == []
    assert presentation["primary_findings"] == []
    assert presentation["review_queue_findings"] == []
    assert presentation["summary"]["primary_finding_count"] == 0
    assert presentation["summary"]["review_queue_finding_count"] == 0

    projected_again = service.with_presentation(understanding)
    assert projected_again is not None
    assert projected_again["presentation"]["findings"] == []
    assert projected_again["presentation"]["primary_findings"] == []
    assert projected_again["presentation"]["review_queue_findings"] == []


def test_with_presentation_filters_low_magnitude_table_row_candidate_from_findings():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": "How do laser power and scan speed affect density?",
            },
            "claims": [],
            "relations": [
                {
                    "relation_id": "rel_laser_density_low_delta",
                    "relation_type": "decreases",
                    "subject": "laser power",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "With scan speed 100 and heat treatment type Furnace HT, "
                        "changing laser power from 100 to 120 decreased density "
                        "from 98.70 % to 98.45 %."
                    ),
                    "status": "supported",
                    "confidence": 0.62,
                    "evidence_ref_ids": ["evref_laser_density"],
                    "context_ids": ["ctx_laser_density"],
                    "source_object_ids": ["unit_laser_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_laser_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_laser_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "variable_process_axes": ["laser power", "scan speed"],
                    },
                    "property_scope": ["density"],
                },
                {
                    "context_id": "ctx_laser_density",
                    "label": "Claim applicability",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "baseline_context": {
                            "process_context": {
                                "Laser power": "100",
                                "Scan speed": "100",
                                "Type of heat treatment": "Furnace HT",
                            },
                            "source_value_text": "98.70 %",
                            "value": 98.70,
                        },
                        "process_context": {
                            "Laser power": "120",
                            "Scan speed": "100",
                            "Type of heat treatment": "Furnace HT",
                        },
                    },
                    "property_scope": ["density"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    presentation = understanding["presentation"]
    assert presentation["findings"] == []
    assert presentation["primary_findings"] == []
    assert presentation["review_queue_findings"] == []
    assert presentation["summary"]["primary_finding_count"] == 0
    assert presentation["summary"]["review_queue_finding_count"] == 0


def test_with_presentation_keeps_uts_table_when_text_only_supports_yield_and_elongation():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            blocks=[
                SourceBlock(
                    block_id="blk-preheat-tensile",
                    document_id="paper-preheat",
                    block_type="paragraph",
                    text=(
                        "Monotonic tensile deformation behavior of specimens "
                        "fabricated with and without preheating is shown in Figure 5. "
                        "The ultimate tensile strength of the present alloy increased "
                        "compared with additively manufactured and wrought counterparts. "
                        "Interestingly, preheating increased elongation and yield "
                        "strength by approximately 14% and 4%, respectively."
                    ),
                    block_order=136,
                    page=7,
                    heading_path="3 Results and discussion",
                )
            ]
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-preheat",
                "goal_id": "goal-preheat",
                "title": "How does build-platform preheating affect tensile properties?",
            },
            "claims": [],
            "relations": [
                {
                    "relation_id": "rel_preheat_uts",
                    "relation_type": "increases",
                    "subject": "build platform preheating temperature",
                    "predicate": "increases",
                    "object": "ultimate tensile strength",
                    "statement": (
                        "Increasing the build platform preheating temperature "
                        "increases ultimate tensile strength."
                    ),
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_uts_table"],
                    "context_ids": ["ctx_objective_scope"],
                    "source_object_ids": ["unit_uts_table"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_uts_table",
                    "source_kind": "table",
                    "document_id": "paper-preheat",
                    "label": "P001 Table 2",
                    "locator": {"source_ref": "tbl-preheat-tensile", "page": 8},
                    "fact_ids": ["unit_uts_table"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Monotonic tensile properties. Non-preheated: 448 | 617 | 72. "
                        "Preheated: 465 | 618 | 82."
                    ),
                },
                {
                    "evidence_ref_id": "evref_tensile_text",
                    "source_kind": "text_window",
                    "document_id": "paper-preheat",
                    "label": "P001 Results",
                    "locator": {"source_ref": "blk-preheat-tensile", "page": 7},
                    "fact_ids": ["unit_tensile_text"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Monotonic tensile deformation behavior is shown in Figure 5. "
                        "The ultimate tensile strength of the present alloy increased "
                        "compared with additively manufactured and wrought counterparts. "
                        "Preheating increased elongation and yield strength by 14% "
                        "and 4%, respectively."
                    ),
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_objective_scope",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "build platform preheating temperature"
                        ]
                    },
                    "property_scope": ["ultimate tensile strength"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    finding = _presentation_finding_by_claim_id(
        understanding,
        "relation_rel_preheat_uts",
    )
    assert finding["statement"] == (
        "Increasing the build platform preheating temperature increases "
        "ultimate tensile strength."
    )
    assert finding["evidence_bundle"]["direct_result"] == ["evref_uts_table"]
    assert "evref_tensile_text" not in finding["evidence_bundle"]["direct_result"]


def test_with_presentation_filters_negligible_uts_table_comparison():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-preheat",
                "goal_id": "goal-preheat",
                "title": "How does build-platform preheating affect tensile properties?",
            },
            "claims": [],
            "relations": [
                {
                    "relation_id": "rel_preheat_uts_negligible",
                    "relation_type": "increases",
                    "subject": "build platform preheating temperature",
                    "predicate": "increases",
                    "object": "ultimate tensile strength",
                    "statement": (
                        "With build conditions controlled, changing build platform "
                        "preheating temperature from 25 to 150 C increased ultimate "
                        "tensile strength from 617 MPa to 618 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.62,
                    "evidence_ref_ids": ["evref_uts_table"],
                    "context_ids": ["ctx_objective_scope"],
                    "source_object_ids": ["unit_uts_table"],
                    "warnings": ["deterministic_relation"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_uts_table",
                    "source_kind": "table",
                    "document_id": "paper-preheat",
                    "label": "P001 Table 2",
                    "locator": {"source_ref": "tbl-preheat-tensile", "page": 8},
                    "fact_ids": ["unit_uts_table"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Ultimate tensile strength: non-preheated 617 MPa; "
                        "preheated 618 MPa."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_objective_scope",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "build platform preheating temperature"
                        ],
                        "baseline_context": {
                            "process_context": {
                                "Build platform preheating temperature": "25 C"
                            },
                            "source_value_text": "617 MPa",
                            "value": 617,
                        },
                        "process_context": {
                            "Build platform preheating temperature": "150 C"
                        },
                    },
                    "property_scope": ["ultimate tensile strength"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    presentation = understanding["presentation"]
    assert any(
        effect["claim_id"] == "relation_rel_preheat_uts_negligible"
        for effect in presentation["effects"]
    )
    assert presentation["findings"] == []
    assert presentation["primary_findings"] == []
    assert presentation["review_queue_findings"] == []


def test_with_presentation_filters_small_density_table_candidate_from_findings():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": "How do heat treatment and scan speed affect density?",
            },
            "claims": [],
            "relations": [
                {
                    "relation_id": "rel_heat_density_small_delta",
                    "relation_type": "increases",
                    "subject": "heat treatment type",
                    "predicate": "increases",
                    "object": "density",
                    "statement": (
                        "With laser power 100 and scan speed 200, changing "
                        "heat treatment type from HIP to Furnace HT increased "
                        "density from 92.63 % to 93.67 %."
                    ),
                    "status": "supported",
                    "confidence": 0.62,
                    "evidence_ref_ids": ["evref_heat_density"],
                    "context_ids": ["ctx_heat_density"],
                    "source_object_ids": ["unit_heat_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_heat_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_heat_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_heat_density",
                    "label": "Claim applicability",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "baseline_context": {
                            "process_context": {
                                "Heat treatment type": "HIP",
                                "Laser power": "100",
                                "Scan speed": "200",
                            },
                            "source_value_text": "92.63 %",
                            "value": 92.63,
                        },
                        "process_context": {
                            "Heat treatment type": "Furnace HT",
                            "Laser power": "100",
                            "Scan speed": "200",
                        },
                    },
                    "property_scope": ["density"],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    presentation = understanding["presentation"]
    assert presentation["findings"] == []
    assert presentation["primary_findings"] == []
    assert presentation["review_queue_findings"] == []
    assert presentation["summary"]["primary_finding_count"] == 0
    assert presentation["summary"]["review_queue_finding_count"] == 0


def test_objective_understanding_filters_small_prediction_only_table_candidate():
    payload = _oversized_relation_payload(unit_count=4)
    payload["objective"]["question"] = (
        "How do scan strategy rotation angle and build orientation affect "
        "yield strength?"
    )
    payload["objective"]["process_axes"] = [
        "scan strategy rotation angle",
        "build orientation",
    ]
    payload["objective"]["property_axes"] = ["yield strength"]
    payload["objective_context"]["target_variable_axes"] = [
        "scan strategy rotation angle",
        "build orientation",
    ]
    payload["objective_context"]["target_property_axes"] = ["yield strength"]
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-beta-yield-small-prediction",
            "document_id": "paper-6",
            "unit_kind": "comparison",
            "property_normalized": "yield strength prediction",
            "process_context": {"β": "22.5", "α": "0", "ɵ": "0", "θ": "0"},
            "baseline_context": {
                "process_context": {"β": "0", "α": "0", "ɵ": "0", "θ": "0"},
                "source_value_text": "310.48",
                "value": 310.48,
            },
            "value_payload": {
                "comparison_axis": "β",
                "controlled_axes": [
                    {"axis": "ɵ", "value": "0"},
                    {"axis": "α", "value": "0"},
                    {"axis": "θ", "value": "0"},
                ],
                "current_value": 314.37,
                "direction": "increase",
                "source_value_text": "314.37",
                "value": 314.37,
            },
            "unit": "MPa",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-texture-yield",
                    "display_label": "P006 Table 3",
                    "role": "current_experimental_evidence",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.91,
        }
    ]
    payload["logic_chain"] = {
        "evidence_unit_ids": ["oeu-beta-yield-small-prediction"],
        "summary": "",
    }
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())

    understanding = service.build_objective_understanding(payload)

    assert understanding["presentation"]["findings"] == []
    assert understanding["presentation"]["primary_findings"] == []
    assert understanding["presentation"]["review_queue_findings"] == []


def test_with_presentation_keeps_table_direct_result_when_same_paper_text_mentions_energy_density():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-density",
                    human_readable_id=4,
                    title="Heat treatment and process density study",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-heat-treatment",
                    document_id="paper-density",
                    block_type="paragraph",
                    text=(
                        "A relatively higher density was obtained by increasing "
                        "the applied laser energy density. Heat treatments "
                        "increased density and removed cellular microstructure."
                    ),
                    block_order=133,
                    page=12,
                    heading_path="4. Conclusions",
                )
            ],
            tables=[
                SourceTable(
                    table_id="tbl-density",
                    document_id="paper-density",
                    table_order=2,
                    caption_text="Table 2. Relative density of SLM samples.",
                    caption_block_id=None,
                    page=6,
                    bbox=None,
                    heading_path="3. Results and discussion",
                    column_headers=(
                        "laser power",
                        "scan speed",
                        "heat treatment type",
                        "density",
                    ),
                    table_matrix=(
                        ("100 W", "200 mm/s", "Furnace HT", "93.67 %"),
                        ("120 W", "200 mm/s", "Furnace HT", "96.84 %"),
                    ),
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": (
                    "How do heat treatment, laser power, and scan speed affect "
                    "density and microstructure of stainless steel 316L?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_laser_density",
                    "claim_type": "comparison",
                    "statement": (
                        "Under heat treatment type furnace ht and scan speed 200, "
                        "laser power 120 increased density from 93.67 % "
                        "(laser power 100) to 96.84 %."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_laser_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_laser_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_laser_density",
                    "relation_type": "increases",
                    "subject": "laser power",
                    "predicate": "increases",
                    "object": "density",
                    "statement": (
                        "Under heat treatment type furnace ht and scan speed 200, "
                        "laser power 120 increased density from 93.67 % "
                        "(laser power 100) to 96.84 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_laser_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_laser_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_heat_treatment",
                    "source_kind": "text_window",
                    "document_id": "paper-density",
                    "label": "P004 Conclusions",
                    "locator": {"source_ref": "blk-heat-treatment"},
                    "fact_ids": ["unit_heat_treatment"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "A relatively higher density was obtained by increasing "
                        "the applied laser energy density. Heat treatments "
                        "increased density and removed cellular microstructure."
                    ),
                },
                {
                    "evidence_ref_id": "evref_laser_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_laser_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "variable_process_axes": [
                            "heat treatment",
                            "laser power",
                            "scan speed",
                        ],
                    },
                    "property_scope": ["density", "microstructure"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = next(
        item
        for item in understanding["presentation"]["findings"]
        if item["claim_id"] == "claim_laser_density"
    )
    assert finding["title"] == "laser power -> density"
    assert finding["evidence_bundle"]["direct_result"] == ["evref_laser_density"]
    assert "evref_heat_treatment" not in finding["evidence_bundle"]["direct_result"]


def test_with_presentation_filters_specimen_label_as_finding_axis():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            tables=[
                SourceTable(
                    table_id="tbl-density",
                    document_id="paper-density",
                    table_order=2,
                    caption_text="Table 2. Relative density of SLM samples.",
                    caption_block_id=None,
                    page=6,
                    bbox=None,
                    heading_path="3. Results",
                    column_headers=("Specimens", "density"),
                    table_matrix=(("100) HIP-SLM", "98.16 %"), ("Specimens", "95.92 %")),
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": "How do processing variables affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_specimens_density",
                    "claim_type": "comparison",
                    "statement": (
                        "Under heat treatment type hip, Specimens decreased "
                        "density from 98.16 % (100) HIP-SLM) to 95.92 %."
                    ),
                    "status": "supported",
                    "confidence": 0.62,
                    "evidence_ref_ids": ["evref_specimens_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_specimens_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_specimens_density",
                    "relation_type": "decreases",
                    "subject": "Specimens",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "Under heat treatment type hip, Specimens decreased "
                        "density from 98.16 % (100) HIP-SLM) to 95.92 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_specimens_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_specimens_density"],
                    "warnings": ["deterministic_relation"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_specimens_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_specimens_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": "",
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {},
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    titles = [
        finding["title"]
        for finding in understanding["presentation"]["findings"]
    ]
    assert "Specimens -> density" not in titles


def test_with_presentation_dedupes_same_table_direct_evidence_for_finding():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            tables=[
                SourceTable(
                    table_id="tbl-density",
                    document_id="paper-density",
                    table_order=2,
                    caption_text="Table 2. Relative density of SLM samples.",
                    caption_block_id=None,
                    page=6,
                    bbox=None,
                    heading_path="3. Results and discussion",
                    column_headers=("laser power", "scan speed", "density"),
                    table_matrix=(
                        ("120 W", "100 mm/s", "98.45 %"),
                        ("140 W", "100 mm/s", "98.33 %"),
                        ("140 W", "200 mm/s", "97.06 %"),
                    ),
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": "How do laser power and scan speed affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_laser_density",
                    "claim_type": "comparison",
                    "statement": (
                        "Under scan speed 100, laser power 140 decreased "
                        "density from 98.45 % (laser power 120) to 98.33 %."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": [
                        "evref_laser_density",
                        "evref_scan_density",
                    ],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_laser_density"],
                },
            ],
            "relations": [
                {
                    "relation_id": "rel_laser_density",
                    "relation_type": "decreases",
                    "subject": "laser power",
                    "predicate": "decreases",
                    "object": "density",
                    "statement": (
                        "Under scan speed 100, laser power 140 decreased "
                        "density from 98.45 % (laser power 120) to 98.33 %."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": [
                        "evref_laser_density",
                        "evref_scan_density",
                    ],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_laser_density"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_laser_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_laser_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Table 2 rows: laser power 120 scan speed 100 density "
                        "98.45; laser power 140 scan speed 100 density 98.33."
                    ),
                },
                {
                    "evidence_ref_id": "evref_scan_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {"source_ref": "tbl-density"},
                    "fact_ids": ["unit_scan_density"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Table 2 rows: scan speed 100 density 98.33; "
                        "scan speed 200 density 97.06."
                    ),
                },
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
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
    finding = understanding["presentation"]["primary_findings"][0]
    assert finding["title"] == "laser power -> density"
    assert finding["evidence_bundle"]["direct_result"] == ["evref_laser_density"]
    assert finding["evidence_bundle"]["uncategorized"] == []
    assert finding["evidence_ref_ids"] == ["evref_laser_density"]


def test_with_presentation_scope_summary_keeps_direct_evidence_conditions():
    source_text = (
        "Three structures of AISI 316L austenitic stainless steel were "
        "additively manufactured using the laser beam powder bed fusion "
        "(PBF-LB) process with varying volumetric energy density (VED) "
        "levels: low (50.8 J/mm3), medium (79.4 J/mm3), and high "
        "(84.3 J/mm3). Increasing VED reduced the defect fraction and "
        "improved fatigue life."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            blocks=[
                SourceBlock(
                    block_id="blk-ved-fatigue",
                    document_id="paper-1",
                    block_type="paragraph",
                    text=source_text,
                    block_order=139,
                    page=10,
                    heading_path="4.2. The influence of defect structure on fatigue strength",
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
                "title": "How does VED affect fatigue strength?",
            },
            "claims": [
                {
                    "claim_id": "claim_ved_fatigue",
                    "claim_type": "finding",
                    "statement": (
                        "Increasing VED reduced defect fraction and improved "
                        "fatigue life."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_ved_fatigue"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_ved_fatigue"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_ved_fatigue",
                    "relation_type": "improves",
                    "subject": "VED",
                    "predicate": "improves",
                    "object": "defect structure -> fatigue strength",
                    "statement": (
                        "Increasing VED reduced defect fraction and improved "
                        "fatigue life."
                    ),
                    "status": "supported",
                    "evidence_ref_ids": ["evref_ved_fatigue"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["unit_ved_fatigue"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_ved_fatigue",
                    "source_kind": "text_window",
                    "document_id": "paper-1",
                    "label": "P003 Results",
                    "locator": {"source_ref": "blk-ved-fatigue"},
                    "fact_ids": ["unit_ved_fatigue"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": source_text,
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["volumetric energy density"]
                    },
                    "property_scope": ["fatigue life"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["primary_findings"][0]
    assert "PBF-LB" in finding["scope_summary"]
    assert "50.8-84.3 J/mm3" in finding["scope_summary"]


def test_objective_understanding_recovers_ved_fatigue_condition_context():
    result_text = (
        "The present results indicate that the increasing VED leads to lower "
        "fraction of defects, slightly smaller defect size and complexity, and "
        "improves slightly the fatigue life, but still the fatigue resistance "
        "remains distinctly lower than that of the wrought 316L steel."
    )
    condition_text = (
        "Three sets of samples were deposited using an SLM 280HL PBF-LB "
        "equipment. By varying the scanning speed and laser power, three "
        "different VED levels, low (L-VED at 50.8 J/mm3), medium (M-VED at "
        "79.4 J/mm3), and high (H-VED at 84.3 J/mm3) were applied."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-ved",
                    human_readable_id=3,
                    title="VED effects on defects and fatigue",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-method-ved",
                    document_id="paper-ved",
                    block_type="paragraph",
                    text=condition_text,
                    block_order=47,
                    page=3,
                    heading_path="2.1. Laser powder bed fusion processing",
                ),
                SourceBlock(
                    block_id="blk-result-ved",
                    document_id="paper-ved",
                    block_type="paragraph",
                    text=result_text,
                    block_order=139,
                    page=10,
                    heading_path="4.2. The influence of defect structure on fatigue strength",
                ),
            ],
            tables=[
                SourceTable(
                    table_id="tbl-ved-parameters",
                    document_id="paper-ved",
                    table_order=2,
                    page=3,
                    caption_text=(
                        "Table 2 Fabrication parameters for 316L samples with "
                        "varying VED."
                    ),
                    caption_block_id=None,
                    bbox=None,
                    heading_path="2.1. Laser powder bed fusion processing",
                    column_headers=[
                        "ID",
                        "VED [J/mm3]",
                        "Laser power [W]",
                        "Scanning speed [mm/s]",
                        "Hatch spacing [μm]",
                        "Layer thickness [μm]",
                    ],
                    table_matrix=[
                        ["L-VED", "50.8", "160", "875", "120", "30"],
                        ["M-VED", "79.4", "190", "800", "100", "30"],
                        ["H-VED", "84.3", "220", "725", "120", "30"],
                        ["Border hatch", "104.2", "100", "400", "80", "30"],
                    ],
                )
            ],
        ),
    )
    payload = _oversized_relation_payload(unit_count=4)
    payload["collection_id"] = "col-ved"
    payload["objective"] = {
        "objective_id": "obj-ved-fatigue",
        "question": (
            "How do volumetric energy density and layer thickness affect defect "
            "structure and fatigue strength of 316L stainless steel?"
        ),
        "material_scope": ["316L stainless steel"],
        "process_axes": ["volumetric energy density", "layer thickness"],
        "property_axes": ["defect structure", "fatigue strength"],
    }
    payload["objective_context"] = {
        "objective_id": "obj-ved-fatigue",
        "question": payload["objective"]["question"],
        "material_scope": ["316L stainless steel"],
        "variable_process_axes": ["volumetric energy density", "layer thickness"],
        "target_property_axes": ["defect structure", "fatigue strength"],
    }
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-ved-fatigue",
            "document_id": "paper-ved",
            "unit_kind": "interpretation",
            "property_normalized": "fatigue strength",
            "value_payload": {"summary": "Increasing VED improves fatigue life."},
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "blk-result-ved",
                    "evidence_role": "direct_support",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.91,
        }
    ]
    payload["logic_chain"] = {"evidence_unit_ids": ["oeu-ved-fatigue"], "summary": ""}

    understanding = service.build_objective_understanding(payload)

    findings = [
        *understanding["presentation"]["primary_findings"],
        *understanding["presentation"]["review_queue_findings"],
    ]
    finding = next(
        item
        for item in findings
        if item["title"]
        == (
            "coupled PBF-LB parameter sets grouped by volumetric energy density "
            "-> fatigue strength"
        )
    )
    assert "does not isolate a VED-only effect" in finding["statement"]
    assert (
        "Laser power, scanning speed, and hatch spacing varied across these VED "
        "groups" in finding["statement"]
    )
    assert "layer thickness remained fixed at 30 μm" in finding["statement"]
    assert "process_conditions_not_isolated" in finding["warnings"]
    assert "single_variable_effect_not_isolated" in finding["review_reasons"]
    condition_refs = finding["evidence_bundle"]["condition_context"]
    assert len(condition_refs) == 2
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    condition_items = [evidence_by_id[ref_id] for ref_id in condition_refs]
    condition_block_item = next(
        item for item in condition_items if item["source_ref"] == "blk-method-ved"
    )
    assert "50.8" in condition_block_item["quote"]
    assert "79.4" in condition_block_item["quote"]
    assert "84.3" in condition_block_item["quote"]
    condition_table_item = next(
        item for item in condition_items if item["source_ref"] == "tbl-ved-parameters"
    )
    assert condition_table_item["evidence_role"] == "condition_context"
    assert condition_table_item["table_audit"]["relevant_rows"] == [
        {
            "row_index": 0,
            "cells": ["L-VED", "50.8", "160", "875", "120", "30"],
            "aligned": True,
        },
        {
            "row_index": 1,
            "cells": ["M-VED", "79.4", "190", "800", "100", "30"],
            "aligned": True,
        },
        {
            "row_index": 2,
            "cells": ["H-VED", "84.3", "220", "725", "120", "30"],
            "aligned": True,
        },
    ]
    recovered_context = next(
        item
        for item in understanding["contexts"]
        if item["context_id"].startswith("ctx_recovered_ved_defects_fatigue_")
    )
    assert recovered_context["process_context"]["variable_process_axes"] == [
        "volumetric energy density",
        "laser power",
        "scanning speed",
        "hatch spacing",
        "layer thickness",
    ]
    assert {
        "axis": "layer thickness",
        "status": "context",
        "finding_id": finding["finding_id"],
    } in understanding["presentation"]["summary"]["axis_coverage"]["variables"]


def test_with_presentation_projects_traceable_table_comparison_as_finding():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-density",
                    human_readable_id=4,
                    title="Heat treatment density study",
                    text="",
                )
            ],
            tables=[
                SourceTable(
                    table_id="table-density",
                    document_id="paper-density",
                    table_order=2,
                    page=4,
                    caption_text="Density of HIP and Furnace HT samples.",
                    caption_block_id=None,
                    bbox=None,
                    heading_path="Results",
                    column_headers=[
                        "Specimens",
                        "Type of heat treatment",
                        "Laser power (W)",
                        "Scan speed (mm/s)",
                        "Laser energy density (J/mm3)",
                        "Density (%)",
                    ],
                    table_matrix=[
                        [
                            "Specimens",
                            "Type of heat treatment",
                            "Laser power (W)",
                            "Scan speed (mm/s)",
                            "Laser energy density (J/mm3)",
                            "Density (%)",
                        ],
                        ["200) as-SLM (120/", "-", "120", "280", "119", "90.04"],
                        [
                            "280) HT-SLM (120/",
                            "Furnace HT",
                            "120",
                            "280",
                            "119",
                            "93.58",
                        ],
                    ],
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-density",
                "goal_id": "goal-density",
                "title": (
                    "How do heat treatment type and laser power affect "
                    "density of stainless steel 316L?"
                ),
            },
            "claims": [
                {
                    "claim_id": "claim_heat_density",
                    "claim_type": "comparison",
                    "statement": (
                        "Under laser power 120 and scan speed 280, heat "
                        "treatment type Furnace HT increased density from "
                        "90.04 % (heat treatment type -) to 93.58 %."
                    ),
                    "status": "supported",
                    "confidence": 0.95,
                    "evidence_ref_ids": ["evref_heat_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu_heat_density"],
                    "warnings": [],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_heat_density",
                    "relation_type": "increases",
                    "subject": "heat treatment",
                    "predicate": "increases",
                    "object": "density",
                    "statement": (
                        "Under laser power 120 and scan speed 280, heat "
                        "treatment type Furnace HT increased density from "
                        "90.04 % (heat treatment type -) to 93.58 %."
                    ),
                    "status": "supported",
                    "confidence": 0.95,
                    "evidence_ref_ids": ["evref_heat_density"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu_heat_density"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_heat_density",
                    "source_kind": "table",
                    "document_id": "paper-density",
                    "label": "P004 Table 2",
                    "locator": {
                        "source_kind": "table",
                        "source_ref": "table-density",
                    },
                    "fact_ids": ["oeu_heat_density"],
                    "traceability_status": "resolved",
                    "quote": None,
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "variable_process_axes": [
                            "heat treatment type",
                            "laser power",
                        ],
                    },
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["findings"][0]
    assert finding["title"] == "heat treatment type -> density"
    assert finding["evidence_bundle"]["direct_result"] == ["evref_heat_density"]
    assert finding["support_grade"] == "partial"
    assert finding["comparison_summary"] == {
        "variable": "heat treatment type",
        "direction": "condition-dependent",
        "outcome": "density",
        "baseline": {
            "label": "heat treatment type -",
            "value": "90.04 %",
        },
        "observed": {
            "label": "heat treatment type Furnace HT",
            "value": "93.58 %",
        },
        "controlled_conditions": [
            {"axis": "laser power", "value": "120"},
            {"axis": "scan speed", "value": "280"},
        ],
    }
    assert understanding["presentation"]["primary_findings"] == []
    review_finding = _presentation_review_finding_by_claim_id(
        understanding,
        "claim_heat_density",
    )
    assert review_finding["title"] == finding["title"]
    assert review_finding["evidence_bundle"]["direct_result"] == [
        "evref_heat_density"
    ]
    assert review_finding["dataset_use_status"] == "review_candidate"
    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert "Specimens:" not in evidence_item["quote"]
    assert "200) as-SLM (120/" not in evidence_item["quote"]
    assert "Type of heat treatment: -" in evidence_item["quote"]
    assert "Density (%): 90.04" in evidence_item["quote"]
    assert (
        "Type of heat treatment: Furnace HT" in evidence_item["quote"]
    )
    assert "Density (%): 93.58" in evidence_item["quote"]
    assert "200) as-SLM (120/" in evidence_item["source_text"]
    assert evidence_item["table_audit"]["columns"] == [
        "Type of heat treatment",
        "Laser power (W)",
        "Scan speed (mm/s)",
        "Laser energy density (J/mm3)",
        "Density (%)",
    ]
    assert evidence_item["table_audit"]["relevant_rows"] == [
        {
            "row_index": 2,
            "cells": ["Furnace HT", "120", "280", "119", "93.58"],
            "aligned": True,
        },
        {
            "row_index": 1,
            "cells": ["-", "120", "280", "119", "90.04"],
            "aligned": True,
        },
    ]
    response_payload = ResearchUnderstandingResponse.model_validate(
        understanding
    ).model_dump()
    assert response_payload["presentation"]["findings"][0][
        "comparison_summary"
    ] == finding["comparison_summary"]


def test_with_presentation_table_audit_keeps_decimal_from_to_endpoint_rows():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-mechanical",
                    human_readable_id=6,
                    title="SLM mechanical properties",
                    text="",
                )
            ],
            tables=[
                SourceTable(
                    table_id="table-mechanical",
                    document_id="paper-mechanical",
                    table_order=4,
                    page=9,
                    caption_text="Mechanical properties of SLM samples.",
                    caption_block_id=None,
                    bbox=None,
                    heading_path="Results",
                    column_headers=[
                        "Specimens",
                        "Hardness (HV)",
                        "Yield Strength (MPa)",
                        "Tensile Strength (MPa)",
                        "Elongation (%)",
                    ],
                    table_matrix=[
                        [
                            "Specimens",
                            "Hardness (HV)",
                            "Yield Strength (MPa)",
                            "Tensile Strength (MPa)",
                            "Elongation (%)",
                        ],
                        [
                            "(100/280) as-SLM(120/",
                            "( +/- 9.2) 196.9",
                            "(10.2) 464.8 (+/- 5.8)",
                            "593.0 (+/- 9.1)",
                            "35.0 (+/- 9.6)",
                        ],
                        [
                            "HIP-SLM (140/100)",
                            "177.7 +/- 4.2",
                            "319.0 (+/- 5.7)",
                            "566.7 (+/- 6.2)",
                            "52.7 (+/- 3.6)",
                        ],
                    ],
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-mechanical",
                "goal_id": "goal-mechanical",
                "title": "How does energy density affect elongation?",
            },
            "claims": [
                {
                    "claim_id": "claim_elongation",
                    "claim_type": "comparison",
                    "statement": (
                        "Under scanning speed 100, energy density 333 decreased "
                        "elongation from 52.7 (+/- 3.6) % "
                        "(energy density 278) to 35.0 %."
                    ),
                    "status": "supported",
                    "confidence": 0.87,
                    "evidence_ref_ids": ["evref_elongation"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu_elongation"],
                    "warnings": [],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_elongation",
                    "relation_type": "decreases",
                    "subject": "energy density",
                    "predicate": "decreases",
                    "object": "elongation",
                    "statement": (
                        "Under scanning speed 100, energy density 333 decreased "
                        "elongation from 52.7 (+/- 3.6) % "
                        "(energy density 278) to 35.0 %."
                    ),
                    "status": "supported",
                    "confidence": 0.87,
                    "evidence_ref_ids": ["evref_elongation"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu_elongation"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_elongation",
                    "source_kind": "table",
                    "document_id": "paper-mechanical",
                    "label": "P006 Table 3",
                    "locator": {
                        "source_kind": "table",
                        "source_ref": "table-mechanical",
                    },
                    "fact_ids": ["oeu_elongation"],
                    "traceability_status": "resolved",
                    "quote": None,
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["stainless steel 316L"],
                    "process_context": {
                        "variable_process_axes": ["energy density"],
                    },
                    "property_scope": ["elongation"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert (
        "Specimens: (100/280) as-SLM(120/; Hardness (HV): ( +/- 9.2) 196.9"
        in evidence_item["quote"]
    )
    assert "Unaligned cells:" not in evidence_item["quote"]
    assert evidence_item["table_audit"]["relevant_rows"] == [
        {
            "row_index": 1,
            "cells": [
                "(100/280) as-SLM(120/",
                "( +/- 9.2) 196.9",
                "(10.2) 464.8 (+/- 5.8)",
                "593.0 (+/- 9.1)",
                "35.0 (+/- 9.6)",
            ],
            "aligned": True,
        },
        {
            "row_index": 2,
            "cells": [
                "HIP-SLM (140/100)",
                "177.7 +/- 4.2",
                "319.0 (+/- 5.7)",
                "566.7 (+/- 6.2)",
                "52.7 (+/- 3.6)",
            ],
            "aligned": True,
        },
    ]


def test_with_presentation_table_quote_does_not_mislabel_short_rows():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-short-row",
                    human_readable_id=7,
                    title="Short table row study",
                    text="",
                )
            ],
            tables=[
                SourceTable(
                    table_id="table-short-row",
                    document_id="paper-short-row",
                    table_order=1,
                    page=2,
                    caption_text="Short rows from parsed table.",
                    caption_block_id=None,
                    bbox=None,
                    heading_path="Results",
                    column_headers=["A", "B", "C"],
                    table_matrix=[["A", "B", "C"], ["10", "20"]],
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-short-row",
                "goal_id": "goal-short-row",
                "title": "How does A affect C?",
            },
            "claims": [
                {
                    "claim_id": "claim_short_row",
                    "claim_type": "comparison",
                    "statement": "A changed from 10 to 20.",
                    "status": "supported",
                    "confidence": 0.7,
                    "evidence_ref_ids": ["evref_short_row"],
                    "context_ids": ["ctx_short_row"],
                    "source_object_ids": ["oeu_short_row"],
                    "warnings": [],
                }
            ],
            "relations": [],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_short_row",
                    "source_kind": "table",
                    "document_id": "paper-short-row",
                    "label": "Table 1",
                    "locator": {
                        "source_kind": "table",
                        "source_ref": "table-short-row",
                    },
                    "fact_ids": ["oeu_short_row"],
                    "traceability_status": "resolved",
                    "quote": None,
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_short_row",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["A"]},
                    "property_scope": ["C"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    evidence_item = understanding["presentation"]["evidence_items"][0]
    assert "Relevant rows: Unaligned cells: 10 | 20" in evidence_item["quote"]
    assert "A: 10; B: 20" not in evidence_item["quote"]
    assert evidence_item["table_audit"]["relevant_rows"] == [
        {
            "row_index": 1,
            "cells": ["10", "20"],
            "aligned": False,
        }
    ]


def test_table_quote_preserves_repeated_cells_for_alignment():
    service = ResearchUnderstandingService(
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-repeated-row",
                    human_readable_id=8,
                    title="Repeated cells table study",
                    text="",
                )
            ],
            tables=[
                SourceTable(
                    table_id="table-repeated-row",
                    document_id="paper-repeated-row",
                    table_order=1,
                    page=2,
                    caption_text="Repeated cells from parsed table.",
                    caption_block_id=None,
                    bbox=None,
                    heading_path="Results",
                    column_headers=["Condition number", "Sample number", "Density"],
                    table_matrix=[
                        ["Condition number", "Sample number", "Density"],
                        ["1", "1", "95.4"],
                    ],
                )
            ],
        )
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-repeated-row",
                "goal_id": "goal-repeated-row",
                "title": "How does condition affect density?",
            },
            "claims": [
                {
                    "claim_id": "claim_repeated_row",
                    "claim_type": "comparison",
                    "statement": "Condition number 1 sample 1 reported density 95.4.",
                    "status": "supported",
                    "confidence": 0.7,
                    "evidence_ref_ids": ["evref_repeated_row"],
                    "context_ids": ["ctx_repeated_row"],
                    "source_object_ids": ["oeu_repeated_row"],
                    "warnings": [],
                }
            ],
            "relations": [],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_repeated_row",
                    "source_kind": "table",
                    "document_id": "paper-repeated-row",
                    "label": "Table 1",
                    "locator": {
                        "source_kind": "table",
                        "source_ref": "table-repeated-row",
                    },
                    "fact_ids": ["oeu_repeated_row"],
                    "traceability_status": "resolved",
                    "quote": None,
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_repeated_row",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {"variable_process_axes": ["condition number"]},
                    "property_scope": ["density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    quote = understanding["presentation"]["evidence_items"][0]["quote"]
    assert "Condition number: 1; Sample number: 1; Density: 95.4" in quote
    assert "Unaligned cells:" not in quote


def test_table_alignment_review_reason_marks_unaligned_direct_table_rows():
    service = ResearchUnderstandingService()
    finding = {
        "finding_id": "finding_short_row",
        "claim_id": "claim_short_row",
        "title": "A -> C",
        "statement": "Under B 20, A increased C from 10 to 30.",
        "variables": ["A"],
        "outcomes": ["C"],
        "mediators": [],
        "evidence_bundle": {
            "direct_result": ["evref_short_row"],
            "mechanism": [],
            "condition_context": [],
            "background": [],
            "conflict": [],
            "noise": [],
            "uncategorized": [],
        },
        "review_reasons": ["single_paper_evidence"],
        "warnings": [],
    }
    evidence_by_id = {
        "evref_short_row": {
            "source_kind": "table",
            "locator": {"source_ref": "table-short-row"},
        }
    }
    tables_by_id = {
        "table-short-row": SourceTable(
            table_id="table-short-row",
            document_id="paper-short-row",
            table_order=1,
            page=2,
            caption_text="Short rows from parsed table.",
            caption_block_id=None,
            bbox=None,
            heading_path="Results",
            column_headers=["A", "B", "C"],
            table_matrix=[["A", "B", "C"], ["10", "20"]],
        )
    }

    updated = service._finding_with_table_alignment_review_reason(
        finding,
        evidence_by_id=evidence_by_id,
        tables_by_id=tables_by_id,
        relations_by_id={},
    )

    assert "table_row_alignment_uncertain" in updated["review_reasons"]
    assert "table_row_alignment_uncertain" in updated["warnings"]
    assert "needs_expert_review" in updated["review_reasons"]


def test_with_presentation_does_not_promote_table_only_semantic_relation():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "limited",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-semantic-table",
                "goal_id": "goal-semantic-table",
                "title": "How does scanning speed affect elongation?",
            },
            "claims": [],
            "relations": [
                {
                    "relation_id": "rel_semantic_table",
                    "relation_type": "conditional",
                    "subject": "scanning speed",
                    "predicate": "mixed",
                    "object": "porosity -> microstructure -> elongation",
                    "statement": (
                        "Condition 6 scanning speed affected elongation through "
                        "porosity and microstructure under specific parameter "
                        "conditions."
                    ),
                    "status": "supported",
                    "confidence": 0.7,
                    "evidence_ref_ids": ["evref_mechanical_table"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu_mechanical_table"],
                    "warnings": ["semantic_relation"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_mechanical_table",
                    "source_kind": "table",
                    "document_id": "paper-1",
                    "label": "P001 mechanical properties",
                    "locator": {"source_ref": "table-mechanical"},
                    "fact_ids": ["oeu_mechanical_table"],
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
                        "variable_process_axes": ["scanning speed"]
                    },
                    "property_scope": ["elongation"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    assert understanding["presentation"]["findings"] == []


def test_with_presentation_does_not_promote_unanchored_numeric_semantic_relation():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "limited",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-semantic-range",
                "goal_id": "goal-semantic-range",
                "title": "How does scan rotation affect yield strength?",
            },
            "claims": [],
            "relations": [
                {
                    "relation_id": "rel_semantic_range",
                    "relation_type": "conditional",
                    "subject": "scan strategy rotation angle",
                    "predicate": "correlates",
                    "object": "yield strength prediction",
                    "statement": (
                        "Variation in scan strategy rotation angle correlates "
                        "with yield strength prediction values ranging from "
                        "310.48 MPa to 356.9 MPa."
                    ),
                    "status": "supported",
                    "confidence": 0.7,
                    "evidence_ref_ids": ["evref_prediction_table"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu_prediction_table"],
                    "warnings": ["semantic_relation"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_prediction_table",
                    "source_kind": "table",
                    "document_id": "paper-texture",
                    "label": "Prediction and experimental yield strength",
                    "locator": {"source_ref": "table-prediction"},
                    "fact_ids": ["oeu_prediction_table"],
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
                        "variable_process_axes": [
                            "scan strategy rotation angle"
                        ]
                    },
                    "property_scope": ["yield strength"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    assert understanding["presentation"]["findings"] == []


def test_with_presentation_does_not_attach_semantic_relation_extra_evidence_to_claim():
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-preheat-evidence",
                "goal_id": "goal-preheat-evidence",
                "title": "How does build platform preheating affect ductility?",
            },
            "claims": [
                {
                    "claim_id": "claim_preheat",
                    "claim_type": "finding",
                    "statement": "Build platform preheating increased ductility by 14%.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu_preheat"],
                    "warnings": [],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_grounded",
                    "relation_type": "increases",
                    "subject": "build platform preheating",
                    "predicate": "increases",
                    "object": "ductility",
                    "statement": "Build platform preheating increased ductility by 14%.",
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu_preheat"],
                    "warnings": [],
                },
                {
                    "relation_id": "rel_preheat_semantic_cross_paper",
                    "relation_type": "increases",
                    "subject": "build platform preheating",
                    "predicate": "increases",
                    "object": "microstructure -> ductility",
                    "statement": (
                        "Build platform preheating increased ductility through "
                        "microstructure evolution."
                    ),
                    "status": "supported",
                    "confidence": 0.8,
                    "evidence_ref_ids": ["evref_preheat", "evref_unrelated_ved"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu_preheat", "oeu_unrelated_ved"],
                    "warnings": ["semantic_relation"],
                },
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_preheat",
                    "source_kind": "paragraph",
                    "document_id": "paper-preheat",
                    "label": "Preheating result",
                    "locator": {"source_ref": "block-preheat"},
                    "fact_ids": ["oeu_preheat"],
                    "quote": "Preheating increased ductility by 14%.",
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                },
                {
                    "evidence_ref_id": "evref_unrelated_ved",
                    "source_kind": "paragraph",
                    "document_id": "paper-fatigue",
                    "label": "Unrelated VED result",
                    "locator": {"source_ref": "block-unrelated-ved"},
                    "fact_ids": ["oeu_unrelated_ved"],
                    "quote": (
                        "Equivalent diameter increased from 81 to 115 um as "
                        "energy density increased from 50.8 to 84 J/mm3."
                    ),
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
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
                    "property_scope": ["ductility"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    findings = understanding["presentation"]["findings"]
    assert len(findings) == 1
    assert findings[0]["relation_ids"] == ["rel_preheat_grounded"]
    assert findings[0]["evidence_bundle"]["direct_result"] == ["evref_preheat"]


def test_with_presentation_projects_property_axis_relation_as_finding():
    corrosion_text = (
        "The porosity level and pore size are factors affecting pitting "
        "corrosion behavior. Samples with fewer pores showed better corrosion "
        "properties and a more stable passive film."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-corrosion",
                    human_readable_id=5,
                    title="Porosity and corrosion in SLM 316L",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-corrosion",
                    document_id="paper-corrosion",
                    block_type="paragraph",
                    text=corrosion_text,
                    block_order=91,
                    page=8,
                    heading_path="4 Conclusion",
                )
            ],
        ),
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "limited",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-corrosion",
                "goal_id": "goal-corrosion",
                "title": (
                    "How do porosity level and pore size affect pitting "
                    "corrosion behavior of 316L stainless steel?"
                ),
            },
            "claims": [],
            "relations": [
                {
                    "relation_id": "rel_porosity_corrosion",
                    "relation_type": "affects",
                    "subject": "selective laser melting",
                    "predicate": "explains",
                    "object": "porosity -> pitting corrosion behavior",
                    "statement": (
                        "porosity level and pore size are factors affecting "
                        "pitting corrosion behavior"
                    ),
                    "status": "supported",
                    "confidence": 0.9,
                    "evidence_ref_ids": ["evref_porosity_corrosion"],
                    "context_ids": ["ctx_goal"],
                    "source_object_ids": ["oeu_porosity_corrosion"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_porosity_corrosion",
                    "source_kind": "text_window",
                    "document_id": "paper-corrosion",
                    "label": "P005 Conclusion",
                    "locator": {
                        "source_kind": "text_window",
                        "source_ref": "blk-corrosion",
                        "page": 8,
                    },
                    "fact_ids": ["oeu_porosity_corrosion"],
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": corrosion_text,
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "process_context_axes": ["selective laser melting"],
                        "variable_process_axes": ["porosity level", "pore size"],
                    },
                    "property_scope": ["pitting corrosion behavior"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    assert understanding is not None
    finding = understanding["presentation"]["primary_findings"][0]
    assert finding["title"] == "porosity level -> pitting corrosion behavior"
    assert finding["variables"] == ["porosity level"]
    assert finding["outcomes"] == ["pitting corrosion behavior"]
    assert finding["statement"] == (
        "Across the tested SLM conditions, lower-porosity samples were associated "
        "with higher pitting potential and a more stable passive film, consistent "
        "with better pitting-corrosion resistance. This paper-level evidence does "
        "not isolate porosity as a causal variable."
    )
    assert finding["direction"] == "associated"
    assert "paper_level_association" in finding["warnings"]
    direct_refs = finding["evidence_bundle"]["direct_result"]
    assert direct_refs == ["evref_recovered_porosity_corrosion_blk-corrosion"]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    assert evidence_by_id[direct_refs[0]]["source_ref"] == "blk-corrosion"
    assert "passive film" in evidence_by_id[direct_refs[0]]["quote"]


def test_objective_understanding_recovers_specific_mechanical_property_table_for_scanning_speed_goal():
    conclusion_text = (
        "The SLM samples processed at higher scanning speed exhibited better "
        "densification, refined microstructure, and excellent mechanical "
        "properties as compared to samples processed with lower scanning speed."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-slm",
                    human_readable_id=1,
                    title=(
                        "Effect of energy density and scanning strategy on "
                        "mechanical properties"
                    ),
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-slm-general-conclusion",
                    document_id="paper-slm",
                    block_type="paragraph",
                    text=(
                        "SLM processing parameters, including scanning strategy, "
                        "scanning speed and energy density, significantly affect "
                        "densification, microstructure and mechanical properties."
                    ),
                    block_order=111,
                    page=12,
                    heading_path="4 Conclusions",
                ),
                SourceBlock(
                    block_id="blk-scan-speed-conclusion",
                    document_id="paper-slm",
                    block_type="paragraph",
                    text=conclusion_text,
                    block_order=115,
                    page=12,
                    heading_path="4 Conclusions",
                )
            ],
            tables=[
                SourceTable(
                    table_id="tbl-processing-parameters",
                    document_id="paper-slm",
                    table_order=1,
                    page=3,
                    caption_text="SLM processing parameters along with relative densities.",
                    caption_block_id=None,
                    bbox=None,
                    heading_path="3 Results and discussion",
                    column_headers=[
                        "Condition number",
                        "Sample number",
                        "Hatch space (mm)",
                        "Scan strategy",
                        "Scanning speed (mm/s)",
                        "Energy density (J/mm 3 )",
                        "Relative density",
                    ],
                    table_matrix=[
                        [
                            "Condition number",
                            "Sample number",
                            "Hatch space (mm)",
                            "Scan strategy",
                            "Scanning speed (mm/s)",
                            "Energy density (J/mm 3 )",
                            "Relative density",
                        ],
                        ["2", "4", "0.114", "A", "0.175", "100", "93.9"],
                        ["3", "5", "0.12", "A", "0.167", "100", "96.2"],
                    ],
                ),
                SourceTable(
                    table_id="tbl-mechanical-properties",
                    document_id="paper-slm",
                    table_order=2,
                    page=3,
                    caption_text=(
                        "Mechanical properties (yield strength, ultimate tensile "
                        "strength, and elongation) of SLM processed samples along "
                        "with microhardness values."
                    ),
                    caption_block_id=None,
                    bbox=None,
                    heading_path="3 Results and discussion",
                    column_headers=[
                        "Condition number",
                        "Sample number",
                        "Yield Strength (MPa)",
                        "Ultimate Tensile Strength (MPa)",
                        "Elongation (%)",
                        "Microhardness (HV)",
                    ],
                    table_matrix=[
                        [
                            "Condition number",
                            "Sample number",
                            "Yield Strength (MPa)",
                            "Ultimate Tensile Strength (MPa)",
                            "Elongation (%)",
                            "Microhardness (HV)",
                        ],
                        ["1", "1", "236.65", "375.13", "7.21", "215.65"],
                        ["2", "4", "341.38", "459.58", "6.62", "219.4"],
                        ["3", "5", "302.24", "384.5", "6.40", "189.1"],
                    ],
                )
            ],
        ),
    )
    payload = _oversized_relation_payload(unit_count=4)
    payload["collection_id"] = "col-slm"
    payload["objective"] = {
        "objective_id": "obj-scan-speed-mechanics",
        "question": (
            "How do scanning strategy, scanning speed, and energy density affect "
            "yield strength, ultimate tensile strength, and elongation of 316L "
            "stainless steel processed via selective laser melting?"
        ),
        "material_scope": ["316L stainless steel"],
        "process_axes": ["scanning strategy", "scanning speed", "energy density"],
        "property_axes": [
            "yield strength",
            "ultimate tensile strength",
            "elongation",
        ],
    }
    payload["objective_context"] = {
        "objective_id": "obj-scan-speed-mechanics",
        "question": payload["objective"]["question"],
        "material_scope": ["316L stainless steel"],
        "variable_process_axes": [
            "scanning strategy",
            "scanning speed",
            "energy density",
        ],
        "target_property_axes": [
            "yield strength",
            "ultimate tensile strength",
            "elongation",
        ],
    }
    payload["evidence_units"] = [
        {
            "evidence_unit_id": "oeu-scan-speed",
            "document_id": "paper-slm",
            "unit_kind": "interpretation",
            "property_normalized": "mechanical properties",
            "value_payload": {"summary": conclusion_text},
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "blk-scan-speed-conclusion",
                    "evidence_role": "direct_support",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.91,
        }
    ]
    payload["logic_chain"] = {"evidence_unit_ids": ["oeu-scan-speed"], "summary": ""}

    understanding = service.build_objective_understanding(payload)

    primary = understanding["presentation"]["primary_findings"]
    finding = primary[0]
    assert finding["title"] == (
        "coupled SLM parameter sets: scanning strategy, scanning speed, hatch "
        "spacing, and energy density -> yield strength, ultimate tensile "
        "strength, and elongation"
    )
    assert finding["variables"] == [
        "coupled SLM parameter sets: scanning strategy, scanning speed, hatch "
        "spacing, and energy density"
    ]
    assert finding["outcomes"] == [
        "yield strength",
        "ultimate tensile strength",
        "elongation",
    ]
    assert (
        "mechanical properties"
        not in {
            item["axis"]
            for item in understanding["presentation"]["summary"]["axis_coverage"][
                "properties"
            ]
        }
    )
    direct_refs = finding["evidence_bundle"]["direct_result"]
    mechanism_refs = finding["evidence_bundle"]["mechanism"]
    assert mechanism_refs == [
        "evref_recovered_scan_speed_density_microstructure_"
        "blk-scan-speed-conclusion"
    ]
    assert "missing_mechanism_evidence" not in finding["review_reasons"]
    evidence_by_id = {
        item["evidence_ref_id"]: item
        for item in understanding["presentation"]["evidence_items"]
    }
    direct_evidence_text = " ".join(evidence_by_id[ref_id]["quote"] for ref_id in direct_refs)
    assert "Yield Strength (MPa)" in direct_evidence_text
    assert "Ultimate Tensile Strength (MPa)" in direct_evidence_text
    assert "Elongation (%)" in direct_evidence_text
    assert "236.65" in direct_evidence_text
    assert "459.58" in direct_evidence_text
    assert "6.40" in direct_evidence_text
    statement = finding["statement"]
    assert "  " not in statement
    assert "Across the tested SLM parameter sets" in statement
    assert "higher-scanning-speed conditions" in statement
    assert "densification" in statement
    assert "microstructure" in statement
    assert "yield strength" in statement
    assert "ultimate tensile strength" in statement
    assert "elongation" in statement
    assert "scan strategy, hatch spacing, and energy density also varied" in statement
    assert "do not isolate a scanning-speed effect" in statement
    assert "scanning speed from 0.167 to 0.175" not in statement
    assert "yield strength (302.24 to 341.38 MPa)" not in statement
    assert "ultimate tensile strength (384.5 to 459.58 MPa)" not in statement
    assert "elongation (6.40 to 6.62%)" not in statement
    assert (
        "associated source table reports yield strength, ultimate tensile "
        "strength, and elongation measurements"
    ) in statement
    assert "Yield Strength 236.65-341.38 MPa" not in statement
    assert "values traceable in the associated source table" not in statement
    assert finding["direction"] == "associated"
    assert "single_variable_effect_not_isolated" in finding["warnings"]
    assert "single_variable_effect_not_isolated" in finding["review_reasons"]
    assert {
        segment["direction"] for segment in finding["relation_chain"]
    } == {"associated"}
    coverage = understanding["presentation"]["summary"]["axis_coverage"]["properties"]
    assert {item["axis"]: item["status"] for item in coverage} == {
        "yield strength": "primary",
        "ultimate tensile strength": "primary",
        "elongation": "primary",
    }
    review_queue = understanding["presentation"]["review_queue_findings"]
    assert all(
        item["statement"] != "scan speed is associated with mechanical properties."
        for item in review_queue
    )
    assert all(
        item["statement"]
        != "SLM processing parameters is associated with mechanical properties."
        for item in review_queue
    )
    assert all(
        item["title"] != "scan speed -> mechanical properties"
        for item in review_queue
    )
    assert all(
        item["title"] != "SLM processing parameters -> mechanical properties"
        for item in review_queue
    )


def test_with_presentation_refreshes_persisted_recovered_mechanical_table_summary():
    conclusion_text = (
        "The SLM samples processed at higher scanning speed exhibited better "
        "densification, refined microstructure, and excellent mechanical "
        "properties as compared to samples processed with lower scanning speed."
    )
    service = ResearchUnderstandingService(
        structured_extractor=_FakeSemanticExtractor(),
        source_artifact_repository=_FakeSourceArtifactRepository(
            documents=[
                SourceDocument(
                    document_id="paper-slm",
                    human_readable_id=1,
                    title="SLM process parameters and mechanical properties",
                    text="",
                )
            ],
            blocks=[
                SourceBlock(
                    block_id="blk-slm-processing",
                    document_id="paper-slm",
                    block_type="paragraph",
                    text=(
                        "All samples used the same layer thickness of 0.05 mm, "
                        "laser power of 100 W, and the hatch spacing reported "
                        "in Table 1."
                    ),
                    block_order=48,
                    page=4,
                    heading_path="2.1 Alloy and SLM processing",
                ),
                SourceBlock(
                    block_id="blk-scan-speed-conclusion",
                    document_id="paper-slm",
                    block_type="paragraph",
                    text=conclusion_text,
                    block_order=115,
                    page=12,
                    heading_path="4 Conclusions",
                )
            ],
            tables=[
                SourceTable(
                    table_id="tbl-processing-parameters",
                    document_id="paper-slm",
                    table_order=1,
                    page=3,
                    caption_text="SLM processing parameters along with relative densities.",
                    caption_block_id=None,
                    bbox=None,
                    heading_path="3 Results and discussion",
                    column_headers=[
                        "Condition number",
                        "Sample number",
                        "Hatch space (mm)",
                        "Scan strategy",
                        "Scanning speed (mm/s)",
                        "Energy density (J/mm 3 )",
                        "Relative density",
                    ],
                    table_matrix=[
                        [
                            "Condition number",
                            "Sample number",
                            "Hatch space (mm)",
                            "Scan strategy",
                            "Scanning speed (mm/s)",
                            "Energy density (J/mm 3 )",
                            "Relative density",
                        ],
                        ["2", "4", "0.114", "A", "0.175", "100", "93.9"],
                        ["3", "5", "0.12", "A", "0.167", "100", "96.2"],
                    ],
                ),
                SourceTable(
                    table_id="tbl-mechanical-properties",
                    document_id="paper-slm",
                    table_order=2,
                    page=3,
                    caption_text=(
                        "Mechanical properties (yield strength, ultimate tensile "
                        "strength, and elongation) of SLM processed samples along "
                        "with microhardness values."
                    ),
                    caption_block_id=None,
                    bbox=None,
                    heading_path="3 Results and discussion",
                    column_headers=[
                        "Condition number",
                        "Sample number",
                        "Yield Strength (MPa)",
                        "Ultimate Tensile Strength (MPa)",
                        "Elongation (%)",
                        "Microhardness (HV)",
                    ],
                    table_matrix=[
                        [
                            "Condition number",
                            "Sample number",
                            "Yield Strength (MPa)",
                            "Ultimate Tensile Strength (MPa)",
                            "Elongation (%)",
                            "Microhardness (HV)",
                        ],
                        ["1", "1", "236.65", "375.13", "7.21", "215.65"],
                        ["2", "4", "341.38", "459.58", "6.62", "219.4"],
                        ["3", "5", "302.24", "384.5", "6.40", "189.1"],
                    ],
                )
            ],
        ),
    )
    old_statement = (
        "Higher scanning speed improved densification and refined the "
        "microstructure. Increasing scanning speed from 0.167 to 0.175 at "
        "energy density 100 and scan strategy A corresponded to higher yield "
        "strength (177.68 to 341.38 MPa), ultimate tensile strength "
        "(203.48 to 459.58 MPa), elongation (3.31 to 6.62%)."
    )
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-slm",
                "goal_id": "goal-scan-speed",
                "title": (
                    "How do scanning strategy, scanning speed, and energy "
                    "density affect yield strength, ultimate tensile strength, "
                    "and elongation of 316L stainless steel processed via "
                    "selective laser melting?"
                ),
            },
            "claims": [
                {
                    "claim_id": (
                        "claim_recovered_scan_speed_density_microstructure_"
                        "blk-scan-speed-conclusion"
                    ),
                    "claim_type": "finding",
                    "statement": old_statement,
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": [
                        (
                            "evref_recovered_scan_speed_density_microstructure_"
                            "blk-scan-speed-conclusion"
                        ),
                    ],
                    "context_ids": [
                        (
                            "ctx_recovered_scan_speed_density_microstructure_"
                            "blk-scan-speed-conclusion"
                        ),
                    ],
                    "source_object_ids": ["blk-scan-speed-conclusion"],
                }
            ],
            "relations": [
                {
                    "relation_id": (
                        "rel_recovered_scan_speed_density_microstructure_"
                        "blk-scan-speed-conclusion"
                    ),
                    "relation_type": "compares",
                    "subject": "scanning speed",
                    "predicate": "controls",
                    "object": "yield strength, ultimate tensile strength, elongation",
                    "statement": old_statement,
                    "status": "supported",
                    "confidence": 0.82,
                    "evidence_ref_ids": [
                        (
                            "evref_recovered_scan_speed_density_microstructure_"
                            "blk-scan-speed-conclusion"
                        ),
                    ],
                    "context_ids": [
                        (
                            "ctx_recovered_scan_speed_density_microstructure_"
                            "blk-scan-speed-conclusion"
                        ),
                    ],
                    "source_object_ids": ["blk-scan-speed-conclusion"],
                    "warnings": ["recovered_from_source_text"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": (
                        "evref_recovered_scan_speed_density_microstructure_"
                        "blk-scan-speed-conclusion"
                    ),
                    "source_kind": "paragraph",
                    "document_id": "paper-slm",
                    "label": "4 Conclusions",
                    "locator": {
                        "source_ref": "blk-scan-speed-conclusion",
                        "source_kind": "paragraph",
                        "page": 12,
                    },
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": conclusion_text,
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_goal",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "scanning strategy",
                            "scanning speed",
                            "energy density",
                        ]
                    },
                    "property_scope": [
                        "yield strength",
                        "ultimate tensile strength",
                        "elongation",
                    ],
                },
                {
                    "context_id": (
                        "ctx_recovered_scan_speed_density_microstructure_"
                        "blk-scan-speed-conclusion"
                    ),
                    "label": "Recovered source scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["scanning speed"]
                    },
                    "property_scope": [
                        "yield strength",
                        "ultimate tensile strength",
                        "elongation",
                    ],
                },
            ],
        }
    )

    understanding = service.with_presentation(stored)

    finding = understanding["presentation"]["primary_findings"][0]
    assert finding["title"] == (
        "coupled SLM parameter sets: scanning strategy, scanning speed, hatch "
        "spacing, and energy density -> yield strength, ultimate tensile "
        "strength, and elongation"
    )
    assert finding["variables"] == [
        "coupled SLM parameter sets: scanning strategy, scanning speed, hatch "
        "spacing, and energy density"
    ]
    statement = finding["statement"]
    assert "  " not in statement
    assert "Across the tested SLM parameter sets" in statement
    assert "higher-scanning-speed conditions" in statement
    assert "densification" in statement
    assert "microstructure" in statement
    assert "yield strength" in statement
    assert "ultimate tensile strength" in statement
    assert "elongation" in statement
    assert "scan strategy, hatch spacing, and energy density also varied" in statement
    assert "do not isolate a scanning-speed effect" in statement
    assert "scanning speed from 0.167 to 0.175" not in statement
    assert "yield strength (302.24 to 341.38 MPa)" not in statement
    assert "ultimate tensile strength (384.5 to 459.58 MPa)" not in statement
    assert "elongation (6.40 to 6.62%)" not in statement
    assert (
        "associated source table reports yield strength, ultimate tensile "
        "strength, and elongation measurements"
    ) in statement
    assert "Yield Strength 236.65-341.38 MPa" not in statement
    assert "values traceable in the associated source table" not in statement
    assert "non_single_variable_table_comparison" in finding["warnings"]
    assert "non_single_variable_table_comparison" in finding["review_reasons"]
    assert "single_variable_effect_not_isolated" in finding["warnings"]
    assert "single_variable_effect_not_isolated" in finding["review_reasons"]
    assert "source_unit_inconsistency" in finding["warnings"]
    assert "source_unit_inconsistency" in finding["review_reasons"]
    assert "source reports scanning speed in mm/s" in statement
    assert "internally consistent with m/s" in statement
    assert "treat the scanning-speed unit as unresolved" in statement
    assert finding["direction"] == "associated"
    assert "slm" in finding["scope_summary"].lower()
    assert all(
        item["axis"] != "selective laser melting"
        for item in understanding["presentation"]["summary"]["axis_coverage"][
            "variables"
        ]
    )
    assert {
        segment["direction"] for segment in finding["relation_chain"]
    } == {"associated"}


def test_with_presentation_comparison_summary_extracts_percent_delta_finding():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-preheat",
                "goal_id": "goal-preheat",
                "title": "How does build platform preheating affect ductility?",
            },
            "claims": [
                {
                    "claim_id": "claim_preheat_ductility",
                    "claim_type": "finding",
                    "statement": (
                        "Preheating the build platform to 150 °C increased "
                        "ductility by 14%, through a more homogenized cellular "
                        "microstructure and GND-assisted plastic deformation."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_preheat"],
                    "source_object_ids": ["oeu_preheat"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_preheat_ductility",
                    "relation_type": "improves",
                    "subject": "build platform preheating temperature",
                    "predicate": "improves",
                    "object": "ductility",
                    "statement": (
                        "Preheating the build platform to 150 °C increased "
                        "ductility by 14%."
                    ),
                    "status": "supported",
                    "confidence": 0.86,
                    "evidence_ref_ids": ["evref_preheat"],
                    "context_ids": ["ctx_preheat"],
                    "source_object_ids": ["oeu_preheat"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_preheat",
                    "source_kind": "paragraph",
                    "document_id": "paper-preheat",
                    "locator": {"source_ref": "blk-preheat"},
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Preheating the build platform to 150 °C increased "
                        "the ductility of material by 14%."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_preheat",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": [
                            "build platform preheating temperature"
                        ]
                    },
                    "property_scope": ["ductility"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    finding = _presentation_finding_by_claim_id(
        understanding,
        "claim_preheat_ductility",
    )
    assert finding["comparison_summary"] == {
        "variable": "build platform preheating temperature",
        "direction": "increases",
        "outcome": "ductility",
        "baseline": {"label": "", "value": "reference"},
        "observed": {
            "label": "build platform preheating temperature 150 °C",
            "value": "+14% ductility",
        },
        "controlled_conditions": [],
    }


def test_with_presentation_comparison_summary_extracts_embedded_from_to_result():
    service = ResearchUnderstandingService(structured_extractor=_FakeSemanticExtractor())
    stored = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col-ved",
                "goal_id": "goal-ved",
                "title": "How does VED affect defect structure?",
            },
            "claims": [
                {
                    "claim_id": "claim_ved_defects",
                    "claim_type": "finding",
                    "statement": (
                        "Increasing VED improved material density from 91.8 % "
                        "to 99.6 % and reduced defect size and complexity."
                    ),
                    "status": "supported",
                    "confidence": 0.84,
                    "evidence_ref_ids": ["evref_ved"],
                    "context_ids": ["ctx_ved"],
                    "source_object_ids": ["oeu_ved"],
                }
            ],
            "relations": [
                {
                    "relation_id": "rel_ved_density",
                    "relation_type": "improves",
                    "subject": "VED",
                    "predicate": "improves",
                    "object": "material density",
                    "statement": (
                        "Increasing VED improved material density from 91.8 % "
                        "to 99.6 %."
                    ),
                    "status": "supported",
                    "confidence": 0.84,
                    "evidence_ref_ids": ["evref_ved"],
                    "context_ids": ["ctx_ved"],
                    "source_object_ids": ["oeu_ved"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "evref_ved",
                    "source_kind": "paragraph",
                    "document_id": "paper-ved",
                    "locator": {"source_ref": "blk-ved"},
                    "traceability_status": "resolved",
                    "evidence_role": "direct_support",
                    "quote": (
                        "Results showed that increasing VED improved material "
                        "density from 91.8 % to 99.6 % and reduced defect size."
                    ),
                }
            ],
            "contexts": [
                {
                    "context_id": "ctx_ved",
                    "label": "Goal scope",
                    "material_scope": ["316L stainless steel"],
                    "process_context": {
                        "variable_process_axes": ["volumetric energy density"]
                    },
                    "property_scope": ["material density"],
                }
            ],
        }
    )

    understanding = service.with_presentation(stored)

    finding = _presentation_finding_by_claim_id(
        understanding,
        "claim_ved_defects",
    )
    assert finding["comparison_summary"] == {
        "variable": "VED",
        "direction": "increases",
        "outcome": "material density",
        "baseline": {"label": "", "value": "91.8 %"},
        "observed": {"label": "VED", "value": "99.6 %"},
        "controlled_conditions": [],
    }
