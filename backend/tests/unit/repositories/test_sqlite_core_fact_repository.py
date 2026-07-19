from __future__ import annotations

from domain.core import (
    CollectionComparableResult,
    ComparableResult,
    ConfirmedGoal,
    ComparisonRowRecord,
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveLogicChain,
    ObjectivePaperFrame,
    PaperSkim,
    ResearchObjective,
    ResearchUnderstanding,
)
from infra.persistence.sqlite import SqliteCoreFactRepository


def test_sqlite_core_fact_repository_round_trips_comparison_facts(tmp_path):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    repository.replace_collection_comparison_artifacts(
        "col_test",
        (_comparable_result(value=640),),
        (_collection_comparable_result(sort_order=2),),
        (_comparison_row(value=640),),
    )
    refreshed = repository.read_collection_facts("col_test")

    assert refreshed.comparison_artifacts_ready is True
    assert refreshed.comparable_results[0].value.numeric_value == 640.0
    assert refreshed.collection_comparable_results[0].sort_order == 2
    assert refreshed.comparison_rows[0].value == 640.0

    repository.replace_collection_comparison_artifacts("col_empty", (), (), ())
    empty_comparison = repository.read_collection_facts("col_empty")

    assert empty_comparison.comparison_artifacts_ready is True
    assert empty_comparison.comparison_rows == ()


def test_sqlite_core_fact_repository_round_trips_research_objectives(tmp_path):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "title": "LPBF 316L corrosion study",
            "source_filename": "paper.pdf",
            "doc_role": "experimental",
            "candidate_materials": ["316L stainless steel"],
            "candidate_processes": ["LPBF", "heat treatment"],
            "candidate_properties": ["corrosion"],
            "changed_variables": ["heat treatment temperature"],
            "possible_objectives": [
                "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?"
            ],
            "evidence_density": "high",
            "confidence": 0.91,
            "warnings": [],
        }
    )
    objective = ResearchObjective.from_mapping(
        {
            "question": "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["LPBF", "heat treatment"],
            "property_axes": ["corrosion"],
            "comparison_intent": "compare as-built and heat-treated corrosion behavior",
            "seed_document_ids": ["paper-1"],
            "excluded_document_ids": [],
            "confidence": 0.88,
            "reason": "paper skim points to a repeated comparison axis",
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["heat treatment"],
            "process_context_axes": ["LPBF"],
            "target_property_axes": ["corrosion"],
            "excluded_property_axes": [],
            "routing_hints": [
                {
                    "table_id": "table-1",
                    "role": "result_table",
                    "matched_property_axes": ["corrosion"],
                }
            ],
            "extraction_guidance": {
                "do_not_treat_as_variables": ["LPBF"],
                "do_not_treat_as_result_properties": ["heat treatment"],
            },
            "confidence": 0.88,
        }
    )
    objective_frame = ObjectivePaperFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "background": "The paper directly studies LPBF 316L corrosion.",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["heat treatment temperature"],
            "measured_property_scope": ["corrosion"],
            "test_environment_scope": ["3.5 wt.% NaCl"],
            "relevant_sections": ["Results"],
            "relevant_tables": ["table-3"],
            "excluded_tables": ["table-1"],
        }
    )
    evidence_route = ObjectiveEvidenceRoute.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-3",
            "role": "current_experimental_evidence",
            "extractable": True,
            "reason": "Table contains corrosion measurements by sample.",
            "table_schema": {"columns": ["sample", "icorr"]},
            "column_roles": {"sample": "sample_key", "icorr": "measurement"},
            "join_keys": {"sample_column": "sample"},
            "join_plan": {"join_on": "sample_label"},
            "confidence": 0.84,
        }
    )
    evidence_unit = ObjectiveEvidenceUnit.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "unit_kind": "measurement",
            "property_normalized": "corrosion_current_density",
            "material_system": {"name": "316L stainless steel"},
            "sample_context": {"label": "HT-SLM"},
            "process_context": {"process": "LPBF", "heat_treatment": "HT"},
            "resolved_condition": {"medium": "3.5 wt.% NaCl"},
            "test_condition": {"method": "potentiodynamic polarization"},
            "value_payload": {"value": 1.2, "kind": "scalar"},
            "unit": "uA/cm2",
            "baseline_context": {"label": "as-built"},
            "source_refs": [{"source_kind": "table", "source_ref": "table-3"}],
            "evidence_anchor_ids": ["anc-1"],
            "join_keys": {"sample_no": "2"},
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    logic_chain = ObjectiveLogicChain.from_mapping(
        {
            "objective_id": objective.objective_id,
            "chain_scope": "paper",
            "document_id": "paper-1",
            "question": objective.question,
            "evidence_unit_ids": [evidence_unit.evidence_unit_id],
            "chain_payload": {"claim": "HT changes corrosion behavior."},
            "summary": "Paper-level evidence chain for LPBF 316L corrosion.",
            "confidence": 0.79,
        }
    )

    repository.replace_collection_research_objectives(
        "col_test",
        (paper_skim,),
        (objective,),
        (objective_context,),
        (objective_frame,),
        (evidence_route,),
        (evidence_unit,),
        (logic_chain,),
    )
    restored = repository.read_collection_facts("col_test")

    assert restored.research_objectives_ready is True
    assert restored.paper_skims[0].candidate_materials == ("316L stainless steel",)
    assert restored.research_objectives[0].objective_id.startswith("obj_")
    assert restored.research_objectives[0].seed_document_ids == ("paper-1",)
    assert restored.objective_contexts[0].objective_id == objective.objective_id
    assert restored.objective_contexts[0].routing_hints[0]["table_id"] == "table-1"
    assert restored.objective_paper_frames[0].relevance == "high"
    assert restored.objective_evidence_routes[0].source_ref == "table-3"
    assert restored.objective_evidence_units[0].resolution_status == "resolved"
    assert restored.objective_logic_chains[0].evidence_unit_ids == (
        evidence_unit.evidence_unit_id,
    )


def test_sqlite_core_fact_repository_does_not_own_paper_facts(tmp_path):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")

    assert not hasattr(repository, "replace_collection_facts")
    assert not hasattr(repository, "replace_collection_document_profiles")
    assert not hasattr(
        repository.read_collection_facts("col_test"), "document_profiles"
    )

    with repository._connection() as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert not any(name.startswith("core_document_profiles") for name in table_names)
    assert not any(name.startswith("core_method_facts") for name in table_names)


def test_sqlite_core_fact_repository_round_trips_research_understandings(tmp_path):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    objective_understanding = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "objective",
                "collection_id": "col_test",
                "objective_id": "obj_strength",
                "title": "How does heat treatment affect strength?",
            },
            "claims": [
                {
                    "claim_id": "claim_strength",
                    "claim_type": "finding",
                    "statement": "Heat treatment improves strength.",
                    "status": "supported",
                    "evidence_ref_ids": ["ev_strength"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "ev_strength",
                    "source_kind": "table",
                    "document_id": "doc-1",
                    "label": "P001 Table 1",
                    "locator": {"source_ref": "Table 1"},
                    "fact_ids": ["oeu-strength"],
                    "traceability_status": "resolved",
                }
            ],
        }
    )
    material_understanding = ResearchUnderstanding.from_mapping(
        {
            "state": "limited",
            "scope": {
                "scope_type": "material",
                "collection_id": "col_test",
                "material_id": "mat-316l",
                "title": "316L stainless steel",
            },
            "claims": [
                {
                    "claim_id": "claim_density",
                    "claim_type": "measurement",
                    "statement": "Density is reported as 99%.",
                    "status": "limited",
                }
            ],
        }
    )

    repository.upsert_research_understanding("col_test", objective_understanding)
    repository.upsert_research_understanding("col_test", material_understanding)

    restored = repository.read_research_understanding(
        "col_test",
        "objective",
        "obj_strength",
    )
    listed = repository.list_research_understandings("col_test", "material")

    assert restored is not None
    assert restored.scope.objective_id == "obj_strength"
    assert restored.claims[0].statement == "Heat treatment improves strength."
    assert restored.evidence_refs[0].locator == {"source_ref": "Table 1"}
    assert [item.scope.material_id for item in listed] == ["mat-316l"]

    repository.replace_collection_research_understandings(
        "col_test",
        (material_understanding,),
    )

    assert (
        repository.read_research_understanding("col_test", "objective", "obj_strength")
        is None
    )
    assert len(repository.list_research_understandings("col_test")) == 1


def test_sqlite_core_fact_repository_round_trips_confirmed_goals(tmp_path):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    goal = ConfirmedGoal.from_mapping(
        {
            "collection_id": "col_test",
            "question": "How does laser power affect density in LPBF AlSi10Mg?",
            "source_type": "user_input",
            "material_hints": ["AlSi10Mg"],
            "process_hints": ["LPBF", "laser power"],
            "property_hints": ["relative density"],
            "source_objective_id": "obj_density",
            "status": "pending",
            "analysis_progress": {
                "phase": "queued",
                "unit": "steps",
            },
        }
    )

    repository.upsert_confirmed_goal(goal)
    restored = repository.read_confirmed_goal("col_test", goal.goal_id)
    listed = repository.list_confirmed_goals("col_test")

    assert restored is not None
    assert restored.goal_id.startswith("goal_")
    assert restored.collection_id == "col_test"
    assert restored.question == "How does laser power affect density in LPBF AlSi10Mg?"
    assert restored.source_type == "user_input"
    assert restored.material_hints == ("AlSi10Mg",)
    assert restored.process_hints == ("LPBF", "laser power")
    assert restored.property_hints == ("relative density",)
    assert restored.source_objective_id == "obj_density"
    assert restored.status == "pending"
    assert restored.analysis_progress == {"phase": "queued", "unit": "steps"}
    assert listed == (restored,)

    repository.upsert_confirmed_goal(
        ConfirmedGoal.from_mapping(
            {
                **restored.to_record(),
                "status": "running",
                "analysis_error": "temporary failure",
                "analysis_progress": {
                    "phase": "objective_evidence_routing_started",
                    "current": 1,
                    "total": 2,
                    "unit": "frames",
                },
            }
        )
    )
    updated = repository.read_confirmed_goal("col_test", goal.goal_id)

    assert updated is not None
    assert updated.status == "running"
    assert updated.analysis_error == "temporary failure"
    assert updated.analysis_progress == {
        "phase": "objective_evidence_routing_started",
        "current": 1,
        "total": 2,
        "unit": "frames",
    }


def _comparable_result(value: int = 620) -> ComparableResult:
    return ComparableResult.from_mapping(
        {
            "comparable_result_id": "cres-1",
            "source_result_id": "res-1",
            "source_document_id": "doc-1",
            "binding": {
                "variant_id": "var-1",
                "baseline_id": "base-1",
                "test_condition_id": "tc-1",
            },
            "normalized_context": {
                "material_system_normalized": "316L stainless steel",
                "process_normalized": "LPBF",
                "baseline_normalized": "as-built",
                "test_condition_normalized": "room temperature tensile",
            },
            "axis": {
                "axis_name": "heat_treatment",
                "axis_value": "HT",
                "axis_unit": None,
            },
            "value": {
                "property_normalized": "yield_strength",
                "result_type": "scalar",
                "numeric_value": value,
                "unit": "MPa",
                "summary": f"{value} MPa",
            },
            "evidence": {
                "direct_anchor_ids": ["anc-1"],
                "contextual_anchor_ids": [],
                "evidence_ids": ["evi-1"],
                "structure_feature_ids": ["feat-1"],
                "characterization_observation_ids": ["obs-1"],
                "traceability_status": "direct",
            },
            "variant_label": "HT-SLM",
            "baseline_reference": "as-built",
            "result_source_type": "table",
            "epistemic_status": "normalized_from_evidence",
            "normalization_version": "comparable_result_v1",
        }
    )


def _collection_comparable_result(sort_order: int = 1) -> CollectionComparableResult:
    return CollectionComparableResult.from_mapping(
        {
            "collection_id": "col_test",
            "comparable_result_id": "cres-1",
            "assessment": {
                "missing_critical_context": [],
                "comparability_basis": ["direct_traceability"],
                "comparability_warnings": [],
                "comparability_status": "comparable",
                "requires_expert_review": False,
                "assessment_epistemic_status": "normalized_from_evidence",
            },
            "epistemic_status": "normalized_from_evidence",
            "included": True,
            "sort_order": sort_order,
            "policy_family": "default_collection_comparison_policy",
            "policy_version": "comparison_policy_v1",
            "comparable_result_normalization_version": "comparable_result_v1",
            "assessment_input_fingerprint": "fp-1",
            "reassessment_triggers": ["assessment_input_changed"],
        }
    )


def _comparison_row(value: int = 620) -> ComparisonRowRecord:
    return ComparisonRowRecord.from_mapping(
        {
            "row_id": "row-1",
            "collection_id": "col_test",
            "comparable_result_id": "cres-1",
            "source_document_id": "doc-1",
            "variant_id": "var-1",
            "variant_label": "HT-SLM",
            "variable_axis": "heat_treatment",
            "variable_value": "HT",
            "baseline_reference": "as-built",
            "result_source_type": "table",
            "result_type": "scalar",
            "result_summary": f"{value} MPa",
            "supporting_evidence_ids": ["evi-1"],
            "supporting_anchor_ids": ["anc-1"],
            "characterization_observation_ids": ["obs-1"],
            "structure_feature_ids": ["feat-1"],
            "material_system_normalized": "316L stainless steel",
            "process_normalized": "LPBF",
            "property_normalized": "yield_strength",
            "baseline_normalized": "as-built",
            "test_condition_normalized": "room temperature tensile",
            "comparability_status": "comparable",
            "comparability_warnings": [],
            "comparability_basis": ["direct_traceability"],
            "requires_expert_review": False,
            "assessment_epistemic_status": "normalized_from_evidence",
            "missing_critical_context": [],
            "value": value,
            "unit": "MPa",
        }
    )
