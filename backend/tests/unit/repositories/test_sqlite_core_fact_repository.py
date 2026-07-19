from __future__ import annotations

from domain.core import (
    CollectionComparableResult,
    ComparableResult,
    ConfirmedGoal,
    ComparisonRowRecord,
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


def test_sqlite_core_fact_repository_does_not_own_research_objectives(tmp_path):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    facts = repository.read_collection_facts("col_test")

    assert not hasattr(repository, "replace_collection_research_objectives")
    assert not hasattr(facts, "research_objectives_ready")
    assert not hasattr(facts, "research_objectives")

    with repository._connection() as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        status_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(core_fact_collection_status)"
            ).fetchall()
        }

    assert not any(name.startswith("core_objective_") for name in table_names)
    assert "core_paper_skims" not in table_names
    assert "core_research_objectives" not in table_names
    assert "research_objectives_ready" not in status_columns


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
