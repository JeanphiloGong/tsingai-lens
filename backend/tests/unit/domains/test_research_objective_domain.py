from __future__ import annotations

import pytest

from domain.core import (
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveLogicChain,
    ObjectivePaperFrame,
    PaperSkim,
    ResearchObjective,
    build_research_objective_id,
    is_question_shaped_objective,
    normalize_objective_confidence,
    normalize_objective_terms,
)


def test_build_research_objective_id_is_stable_for_same_question() -> None:
    question = "How does heat treatment affect corrosion resistance of LPBF 316L?"

    assert build_research_objective_id(question) == build_research_objective_id(question)
    assert build_research_objective_id(question).startswith(
        "obj_how-does-heat-treatment-affect-corrosion-resistance"
    )


def test_research_objective_normalizes_mapping_and_round_trips_record() -> None:
    objective = ResearchObjective.from_mapping(
        {
            "question": "How does heat treatment affect corrosion resistance of LPBF 316L?",
            "material_scope": ["316L stainless steel", "316L stainless steel", ""],
            "process_axes": ["LPBF", "SLM", None],
            "property_axes": ("corrosion", "EIS"),
            "comparison_intent": "compare as-built and heat-treated samples",
            "seed_document_ids": ["P001", "P002"],
            "excluded_document_ids": ["P005"],
            "confidence": 1.2,
            "reason": "Multiple experimental papers report corrosion results.",
        }
    )

    record = objective.to_record()
    assert record["objective_id"] == build_research_objective_id(record["question"])
    assert record["material_scope"] == ["316L stainless steel"]
    assert record["process_axes"] == ["LPBF", "SLM"]
    assert record["property_axes"] == ["corrosion", "EIS"]
    assert record["confidence"] == 1.0
    assert is_question_shaped_objective(objective) is True


def test_paper_skim_normalizes_missing_and_repeated_values() -> None:
    skim = PaperSkim.from_mapping(
        {
            "paper_id": "P001",
            "title": "  LPBF 316L corrosion study  ",
            "source_filename": "",
            "doc_role": "experimental",
            "candidate_materials": ["316L SS", "316L SS", None],
            "candidate_processes": None,
            "candidate_properties": ("corrosion", "", "corrosion"),
            "changed_variables": float("nan"),
            "possible_objectives": ["Heat treatment effect on corrosion"],
            "confidence": "0.83",
            "warnings": ["table captions missing", "table captions missing"],
        }
    )

    assert skim.document_id == "P001"
    assert skim.title == "LPBF 316L corrosion study"
    assert skim.source_filename is None
    assert skim.candidate_materials == ("316L SS",)
    assert skim.candidate_processes == ()
    assert skim.candidate_properties == ("corrosion",)
    assert skim.changed_variables == ()
    assert skim.confidence == 0.83
    assert skim.to_record()["warnings"] == ["table captions missing"]


def test_question_shaped_objective_rejects_bare_material_name() -> None:
    bare_material = ResearchObjective.from_mapping(
        {
            "question": "316L stainless steel",
            "material_scope": ["316L stainless steel"],
        }
    )
    comparison_question = ResearchObjective.from_mapping(
        {
            "question": "How does heat treatment affect corrosion resistance of LPBF 316L?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["heat treatment"],
            "property_axes": ["corrosion"],
        }
    )

    assert is_question_shaped_objective(bare_material) is False
    assert is_question_shaped_objective(comparison_question) is True


def test_objective_context_round_trips_routing_and_guidance() -> None:
    context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj_1",
            "question": "How does scan speed affect density of LPBF 316L?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["scan speed"],
            "process_context_axes": ["LPBF"],
            "target_property_axes": ["relative density"],
            "excluded_property_axes": ["yield strength"],
            "objective_evidence_lens": {
                "target_outcome_axes": ["relative density"],
                "mediator_axes": ["porosity"],
                "variable_process_axes": ["scan speed"],
                "context_axes": ["316L stainless steel", "LPBF"],
                "excluded_axes": ["yield strength"],
                "direct_support_rules": [
                    "Direct support must explicitly report relative density."
                ],
            },
            "routing_hints": [
                {
                    "table_id": "table_1",
                    "role": "result_table",
                    "matched_property_axes": ["relative density"],
                }
            ],
            "extraction_guidance": {
                "do_not_extract_as_target_results": ["yield strength"],
            },
            "confidence": "0.82",
        }
    )

    record = context.to_record()
    assert record["variable_process_axes"] == ["scan speed"]
    assert record["process_context_axes"] == ["LPBF"]
    assert record["objective_evidence_lens"]["target_outcome_axes"] == [
        "relative density"
    ]
    assert record["objective_evidence_lens"]["mediator_axes"] == ["porosity"]
    assert record["routing_hints"][0]["table_id"] == "table_1"
    assert record["extraction_guidance"]["do_not_extract_as_target_results"] == [
        "yield strength"
    ]
    assert record["confidence"] == 0.82


def test_objective_context_derives_default_evidence_lens_for_old_records() -> None:
    context = ObjectiveContext.from_mapping(
        {
            "objective_id": "obj_legacy",
            "question": "How does scan speed affect density of LPBF 316L?",
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["scan speed"],
            "process_context_axes": ["LPBF"],
            "target_property_axes": ["relative density"],
            "excluded_property_axes": ["yield strength"],
        }
    )

    assert context.objective_evidence_lens["target_outcome_axes"] == [
        "relative density"
    ]
    assert context.objective_evidence_lens["variable_process_axes"] == ["scan speed"]
    assert context.objective_evidence_lens["context_axes"] == [
        "316L stainless steel",
        "LPBF",
    ]
    assert context.objective_evidence_lens["excluded_axes"] == ["yield strength"]


@pytest.mark.parametrize(
    ("relevance", "paper_role"),
    [
        ("high", "primary_experiment"),
        ("low", "supporting_background"),
        ("irrelevant", "irrelevant"),
    ],
)
def test_objective_paper_frame_represents_relevance_states(
    relevance: str,
    paper_role: str,
) -> None:
    frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": "obj_1",
            "document_id": "P001",
            "relevance": relevance,
            "paper_role": paper_role,
            "background": "Paper-specific relationship to this objective.",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment temperature"],
            "measured_property_scope": ["corrosion current density"],
            "test_environment_scope": ["3.5 wt.% NaCl"],
            "relevant_sections": ["Results"],
            "relevant_tables": ["table_3"],
            "excluded_tables": ["table_1"],
        }
    )

    record = frame.to_record()
    assert record["relevance"] == relevance
    assert record["paper_role"] == paper_role
    assert record["relevant_tables"] == ["table_3"]
    assert record["excluded_tables"] == ["table_1"]


@pytest.mark.parametrize(
    ("source_kind", "role", "extractable"),
    [
        ("text_window", "process_or_treatment", True),
        ("table", "current_experimental_evidence", True),
        ("figure", "low_value_or_irrelevant", False),
    ],
)
def test_objective_evidence_route_represents_source_units_and_extractability(
    source_kind: str,
    role: str,
    extractable: bool,
) -> None:
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj_1",
            "document_id": "P001",
            "source_kind": source_kind,
            "source_ref": "table_3",
            "role": role,
            "extractable": extractable,
            "reason": "Relevant to objective.",
            "table_schema": {"columns": ["Sample", "UTS"]},
            "column_roles": {"UTS": "measurement"},
            "confidence": 0.75,
        }
    )

    record = route.to_record()
    assert record["source_kind"] == source_kind
    assert record["role"] == role
    assert record["extractable"] is extractable
    assert record["table_schema"] == {"columns": ["Sample", "UTS"]}
    assert record["column_roles"] == {"UTS": "measurement"}
    assert record["confidence"] == 0.75


def test_objective_evidence_route_normalizes_false_string_and_invalid_role() -> None:
    route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": "obj_1",
            "document_id": "P001",
            "source_kind": "table",
            "source_ref": "table_1",
            "role": "unknown role",
            "extractable": "false",
            "confidence": -1,
        }
    )

    assert route.role == "low_value_or_irrelevant"
    assert route.extractable is False
    assert route.confidence == 0.0


def test_objective_evidence_unit_round_trips_resolved_evidence_payload() -> None:
    unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "objective_id": "obj_1",
            "document_id": "P001",
            "unit_kind": "measurement",
            "property_normalized": "ultimate_tensile_strength",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"label": "HT-SLM"},
            "process_context": {"process": "SLM", "heat_treatment": "1100 C"},
            "resolved_condition": {"temperature": "room temperature"},
            "test_condition": {"method": "tensile"},
            "value_payload": {"value": 713, "kind": "scalar"},
            "unit": "MPa",
            "baseline_context": {"label": "as-SLM"},
            "interpretation": "Heat treatment increases ductility.",
            "source_refs": [{"source_kind": "table", "source_ref": "table_3"}],
            "evidence_anchor_ids": ["anc_1"],
            "join_keys": {"sample_no": "3"},
            "resolution_status": "resolved",
            "confidence": 0.81,
        }
    )

    record = unit.to_record()
    assert record["evidence_unit_id"].startswith("oeu_")
    assert record["property_normalized"] == "ultimate_tensile_strength"
    assert record["sample_context"] == {"label": "HT-SLM"}
    assert record["value_payload"] == {"value": 713, "kind": "scalar"}
    assert record["source_refs"] == [{"source_kind": "table", "source_ref": "table_3"}]
    assert record["resolution_status"] == "resolved"


def test_objective_logic_chain_round_trips_chain_payload() -> None:
    chain = ObjectiveLogicChain.from_mapping(
        {
            "objective_id": "obj_1",
            "chain_scope": "paper",
            "document_id": "P001",
            "question": "How does heat treatment affect LPBF 316L strength?",
            "evidence_unit_ids": ["oeu_1", "oeu_2"],
            "chain_payload": {
                "claim": "Heat treatment changes strength and ductility.",
                "steps": ["process", "microstructure", "property"],
            },
            "summary": "Paper-level logic chain.",
            "confidence": 0.77,
        }
    )

    record = chain.to_record()
    assert record["logic_chain_id"].startswith("olc_")
    assert record["chain_scope"] == "paper"
    assert record["evidence_unit_ids"] == ["oeu_1", "oeu_2"]
    assert record["chain_payload"]["steps"] == ["process", "microstructure", "property"]


def test_objective_term_and_confidence_helpers_are_domain_pure_normalizers() -> None:
    assert normalize_objective_terms(["LPBF", "lpbf", "", None, "SLM"]) == (
        "LPBF",
        "SLM",
    )
    assert normalize_objective_confidence("0.456") == 0.46
    assert normalize_objective_confidence(float("nan")) == 0.0
