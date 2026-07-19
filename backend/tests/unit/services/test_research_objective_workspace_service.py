from __future__ import annotations

import pytest

from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveNotFoundError,
    ResearchObjectiveService,
)
from tests.support.collection_service import build_test_collection_service
from domain.core import (
    CoreFactSet,
    DocumentProfile,
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveLogicChain,
    ObjectivePaperFrame,
    PaperSkim,
    ResearchObjective,
)
from infra.persistence.sqlite.core_fact_repository import SqliteCoreFactRepository
from infra.persistence.sqlite.source_artifact_repository import (
    SqliteSourceArtifactRepository,
)


def _seed_objective_collection(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    collection = collection_service.create_collection("Objective Workspace")
    collection_id = collection["collection_id"]
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    objective = ResearchObjective.from_mapping(
        {
            "question": "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["LPBF", "heat treatment"],
            "property_axes": ["corrosion resistance"],
            "comparison_intent": "Compare as-built and heat-treated samples.",
            "seed_document_ids": ["paper-1"],
            "confidence": 0.88,
        }
    )
    repository.replace_collection_research_objectives(
        collection_id,
        (
            PaperSkim.from_mapping(
                {
                    "document_id": "paper-1",
                    "title": "LPBF 316L Corrosion",
                    "source_filename": "paper-1.pdf",
                    "doc_role": "experimental",
                    "candidate_materials": ["316L stainless steel"],
                }
            ),
        ),
        (objective,),
        (
            ObjectiveContext.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "question": objective.question,
                    "material_scope": ["316L stainless steel"],
                    "variable_process_axes": ["heat treatment"],
                    "process_context_axes": ["LPBF"],
                    "target_property_axes": ["corrosion resistance"],
                    "confidence": 0.88,
                }
            ),
        ),
        (
            ObjectivePaperFrame.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "relevance": "high",
                    "paper_role": "primary_experiment",
                    "background": "Studies LPBF 316L corrosion after heat treatment.",
                    "material_match": ["316L stainless steel"],
                    "changed_variables": ["heat treatment"],
                    "measured_property_scope": ["corrosion resistance"],
                    "test_environment_scope": ["NaCl"],
                    "relevant_sections": ["Results"],
                    "relevant_tables": ["table-1"],
                }
            ),
        ),
        (
            ObjectiveEvidenceRoute.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "document_id": "paper-1",
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "role": "current_experimental_evidence",
                    "extractable": True,
                    "reason": "Contains corrosion results.",
                    "table_schema": {"column_headers": ["sample", "icorr"]},
                    "confidence": 0.81,
                }
            ),
        ),
        (),
        (),
    )
    repository.replace_collection_facts(
        collection_id,
        CoreFactSet(
            document_profiles=(
                DocumentProfile(
                    document_id="paper-1",
                    collection_id=collection_id,
                    title="Profile Title",
                    source_filename="profile-paper.pdf",
                    doc_type="experimental",
                    parsing_warnings=(),
                    confidence=0.9,
                ),
            ),
        ),
    )
    source_repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    service = ResearchObjectiveService(
        collection_service=collection_service,
        core_fact_repository=repository,
        source_artifact_repository=source_repository,
        source_reference_repository=source_repository,
    )
    service.persist_objective_understandings(collection_id)
    return collection_id, objective.objective_id, service


def test_objective_workspace_lists_persisted_objectives(tmp_path):
    collection_id, objective_id, service = _seed_objective_collection(tmp_path)

    payload = service.list_objective_workspaces(collection_id)

    assert payload["collection_id"] == collection_id
    assert payload["state"] == "partial"
    assert payload["readiness"] == {
        "objectives_ready": True,
        "frames_ready": True,
        "routes_ready": True,
        "evidence_units_ready": False,
        "logic_chain_ready": False,
    }
    assert payload["objectives"][0]["objective_id"] == objective_id
    assert payload["objectives"][0]["paper_frame_count"] == 1
    assert payload["objectives"][0]["evidence_route_count"] == 1


def test_objective_workspace_detail_returns_frames_and_reserved_fields(tmp_path):
    collection_id, objective_id, service = _seed_objective_collection(tmp_path)

    payload = service.get_objective_research_view(collection_id, objective_id)

    assert payload["collection_id"] == collection_id
    assert payload["objective"]["objective_id"] == objective_id
    assert payload["objective_context"]["variable_process_axes"] == ["heat treatment"]
    assert payload["paper_frames"][0]["title"] == "Profile Title"
    assert payload["paper_frames"][0]["source_filename"] == "profile-paper.pdf"
    assert payload["paper_frames"][0]["relevant_tables"] == ["table-1"]
    assert payload["evidence_routes"][0]["source_ref"] == "table-1"
    assert payload["evidence_units"] == []
    assert payload["logic_chain"] is None
    assert payload["existing_comparison_rows"] == []
    assert payload["understanding"]["state"] == "empty"
    assert payload["understanding"]["scope"]["scope_type"] == "objective"
    assert payload["understanding"]["scope"]["objective_id"] == objective_id


def test_objective_workspace_detail_filters_non_target_evidence_units(tmp_path):
    collection_id, objective_id, service = _seed_objective_collection(tmp_path)
    facts = service.core_fact_repository.read_collection_facts(collection_id)
    corrosion_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-corrosion",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "corrosion potential",
            "sample_context": {"sample": "135 W-750 mm/s"},
            "value_payload": {"source_value_text": "-243.8", "value": -243.8},
            "unit": "mV",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.91,
        }
    )
    elongation_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-elongation",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "elongation",
            "sample_context": {"sample": "135 W-750 mm/s"},
            "value_payload": {
                "source_value_text": (
                    "The ductility of the 135 W-750 mm/s sample increased "
                    "by about 10%."
                )
            },
            "resolution_status": "resolved",
            "confidence": 0.71,
        }
    )
    density_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-density",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "relative density",
            "sample_context": {"sample": "135 W-750 mm/s"},
            "value_payload": {"source_value_text": "99.26", "value": 99.26},
            "unit": "%",
            "resolution_status": "resolved",
            "confidence": 0.83,
        }
    )
    service.core_fact_repository.replace_collection_research_objectives(
        collection_id,
        facts.paper_skims,
        facts.research_objectives,
        facts.objective_contexts,
        facts.objective_paper_frames,
        facts.objective_evidence_routes,
        (
            corrosion_unit,
            elongation_unit,
            density_unit,
        ),
        (
            ObjectiveLogicChain.from_mapping(
                {
                    "objective_id": objective_id,
                    "chain_scope": "objective",
                    "question": facts.research_objectives[0].question,
                    "evidence_unit_ids": [
                        corrosion_unit.evidence_unit_id,
                        elongation_unit.evidence_unit_id,
                        density_unit.evidence_unit_id,
                    ],
                    "chain_payload": {
                        "measurement_value_ranges": [
                            {"property_normalized": "elongation"},
                            {"property_normalized": "relative density"},
                        ]
                    },
                    "summary": "Polluted persisted logic chain.",
                    "confidence": 0.7,
                }
            ),
        ),
    )
    service.persist_objective_understandings(collection_id)

    payload = service.get_objective_research_view(collection_id, objective_id)

    assert [unit["evidence_unit_id"] for unit in payload["evidence_units"]] == [
        "oeu-corrosion"
    ]
    logic_chain = payload["logic_chain"]
    assert logic_chain is not None
    assert logic_chain["evidence_unit_ids"] == ["oeu-corrosion"]
    assert "corrosion potential range -243.8--243.8 mV" in logic_chain["summary"]
    assert "elongation" not in str(logic_chain)
    assert "relative density" not in str(logic_chain)
    assert "ductility" not in str(logic_chain)


def test_objective_workspace_detail_returns_research_understanding(tmp_path):
    collection_id, objective_id, service = _seed_objective_collection(tmp_path)
    facts = service.core_fact_repository.read_collection_facts(collection_id)
    measurement = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-corrosion",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "corrosion potential",
            "sample_context": {"sample": "as-built"},
            "process_context": {"heat treatment": "none"},
            "value_payload": {"source_value_text": "-243.8", "value": -243.8},
            "unit": "mV",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.91,
        }
    )
    comparison = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-comparison",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "unit_kind": "comparison",
            "property_normalized": "corrosion potential",
            "sample_context": {"sample": "heat-treated"},
            "process_context": {"heat treatment": "annealed"},
            "baseline_context": {"sample": "as-built"},
            "value_payload": {
                "comparison_axis": "heat treatment",
                "direction": "increase",
                "source_value_text": "heat treatment improves corrosion resistance",
            },
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.82,
        }
    )
    mechanism = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-mechanism",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "unit_kind": "characterization",
            "property_normalized": "corrosion resistance",
            "sample_context": {"sample": "heat-treated"},
            "process_context": {"heat treatment": "annealed"},
            "value_payload": {
                "source_value_text": (
                    "heat treatment changed the passive film because chromium "
                    "enrichment improved corrosion resistance"
                )
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-3",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.77,
        }
    )
    service.core_fact_repository.replace_collection_research_objectives(
        collection_id,
        facts.paper_skims,
        facts.research_objectives,
        facts.objective_contexts,
        facts.objective_paper_frames,
        facts.objective_evidence_routes,
        (measurement, comparison, mechanism),
        (
            ObjectiveLogicChain.from_mapping(
                {
                    "objective_id": objective_id,
                    "chain_scope": "objective",
                    "question": facts.research_objectives[0].question,
                    "evidence_unit_ids": [
                        measurement.evidence_unit_id,
                        comparison.evidence_unit_id,
                        mechanism.evidence_unit_id,
                    ],
                    "chain_payload": {},
                    "summary": "Persisted summary.",
                    "confidence": 0.7,
                }
            ),
        ),
    )
    service.persist_objective_understandings(collection_id)

    payload = service.get_objective_research_view(collection_id, objective_id)

    understanding = payload["understanding"]
    assert understanding["state"] == "ready"
    assert understanding["scope"]["scope_type"] == "objective"
    assert understanding["scope"]["objective_id"] == objective_id
    assert understanding["claims"][0]["evidence_ref_ids"]
    assert understanding["relations"][0]["relation_type"] in {"improves", "increases"}
    assert understanding["relations"][0]["subject"] == "heat treatment"
    assert understanding["relations"][0]["evidence_ref_ids"]
    assert any(
        evidence_ref["fact_ids"] == ["oeu-corrosion"]
        for evidence_ref in understanding["evidence_refs"]
    )


def test_objective_workspace_detail_filters_textual_measurement_without_numeric_value(
    tmp_path,
):
    collection_id, objective_id, service = _seed_objective_collection(tmp_path)
    facts = service.core_fact_repository.read_collection_facts(collection_id)
    explicit_elongation_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-elongation-value",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "elongation",
            "sample_context": {"sample": "S1"},
            "value_payload": {"source_value_text": "33 %", "value": 33.0},
            "unit": "%",
            "resolution_status": "resolved",
            "confidence": 0.91,
        }
    )
    textual_elongation_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-elongation-text",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "elongation",
            "sample_context": {"sample": "135 W-750 mm/s"},
            "value_payload": {
                "source_value_text": (
                    "The relatively low porosity levels in the 135 W-750 mm/s "
                    "sample increase the ductility by about 10%."
                )
            },
            "unit": "%",
            "resolution_status": "resolved",
            "confidence": 0.71,
        }
    )
    service.core_fact_repository.replace_collection_research_objectives(
        collection_id,
        facts.paper_skims,
        facts.research_objectives,
        (
            ObjectiveContext.from_mapping(
                {
                    **facts.objective_contexts[0].to_record(),
                    "target_property_axes": ["elongation"],
                }
            ),
        ),
        facts.objective_paper_frames,
        facts.objective_evidence_routes,
        (
            explicit_elongation_unit,
            textual_elongation_unit,
        ),
        (
            ObjectiveLogicChain.from_mapping(
                {
                    "objective_id": objective_id,
                    "chain_scope": "objective",
                    "question": facts.research_objectives[0].question,
                    "evidence_unit_ids": [
                        explicit_elongation_unit.evidence_unit_id,
                        textual_elongation_unit.evidence_unit_id,
                    ],
                    "chain_payload": {},
                    "summary": "Polluted persisted logic chain.",
                    "confidence": 0.7,
                }
            ),
        ),
    )

    payload = service.get_objective_research_view(collection_id, objective_id)

    assert [unit["evidence_unit_id"] for unit in payload["evidence_units"]] == [
        "oeu-elongation-value"
    ]
    logic_chain = payload["logic_chain"]
    assert logic_chain is not None
    assert logic_chain["evidence_unit_ids"] == ["oeu-elongation-value"]
    assert "elongation range 33.0-33.0 %" in logic_chain["summary"]
    assert "ductility" not in str(logic_chain)
    assert "135 W-750" not in str(logic_chain)


def test_objective_workspace_detail_filters_relative_change_interpretation(
    tmp_path,
):
    collection_id, objective_id, service = _seed_objective_collection(tmp_path)
    facts = service.core_fact_repository.read_collection_facts(collection_id)
    explicit_elongation_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-elongation-value",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "elongation",
            "sample_context": {"sample": "S1"},
            "value_payload": {"source_value_text": "33 %", "value": 33.0},
            "unit": "%",
            "resolution_status": "resolved",
            "confidence": 0.91,
        }
    )
    relative_change_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "evidence_unit_id": "oeu-ductility-relative-change",
            "objective_id": objective_id,
            "document_id": "paper-1",
            "unit_kind": "interpretation",
            "property_normalized": "elongation",
            "sample_context": {"laser_power": "135 W", "scan_speed": "750 mm/s"},
            "value_payload": {
                "source_value_numeric": 10,
                "source_value_text": (
                    "The ductility of the 135 W-750 mm/s sample increased "
                    "by about 10%."
                ),
            },
            "unit": "%",
            "resolution_status": "resolved",
            "confidence": 0.62,
        }
    )
    service.core_fact_repository.replace_collection_research_objectives(
        collection_id,
        facts.paper_skims,
        facts.research_objectives,
        (
            ObjectiveContext.from_mapping(
                {
                    **facts.objective_contexts[0].to_record(),
                    "target_property_axes": ["elongation"],
                }
            ),
        ),
        facts.objective_paper_frames,
        facts.objective_evidence_routes,
        (
            explicit_elongation_unit,
            relative_change_unit,
        ),
        (
            ObjectiveLogicChain.from_mapping(
                {
                    "objective_id": objective_id,
                    "chain_scope": "objective",
                    "question": facts.research_objectives[0].question,
                    "evidence_unit_ids": [
                        explicit_elongation_unit.evidence_unit_id,
                        relative_change_unit.evidence_unit_id,
                    ],
                    "chain_payload": {},
                    "summary": "Polluted persisted logic chain.",
                    "confidence": 0.7,
                }
            ),
        ),
    )

    payload = service.get_objective_research_view(collection_id, objective_id)

    assert [unit["evidence_unit_id"] for unit in payload["evidence_units"]] == [
        "oeu-elongation-value"
    ]
    logic_chain = payload["logic_chain"]
    assert logic_chain is not None
    assert logic_chain["evidence_unit_ids"] == ["oeu-elongation-value"]
    assert "elongation range 33.0-33.0 %" in logic_chain["summary"]
    assert "ductility" not in str(logic_chain)
    assert "135 W-750" not in str(logic_chain)


def test_objective_workspace_detail_raises_for_missing_objective(tmp_path):
    collection_id, _, service = _seed_objective_collection(tmp_path)

    with pytest.raises(ResearchObjectiveNotFoundError) as exc_info:
        service.get_objective_research_view(collection_id, "obj_missing")

    assert exc_info.value.collection_id == collection_id
    assert exc_info.value.objective_id == "obj_missing"
