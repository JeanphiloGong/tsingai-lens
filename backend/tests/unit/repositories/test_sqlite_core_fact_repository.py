from __future__ import annotations

from domain.core import (
    ConfirmedGoal,
    ResearchUnderstanding,
)
from infra.persistence.sqlite import SqliteCoreFactRepository


def test_sqlite_core_fact_repository_does_not_own_semantic_build_facts(tmp_path):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    repository._ensure_schema()

    assert not hasattr(repository, "replace_collection_research_objectives")
    assert not hasattr(repository, "replace_collection_comparison_artifacts")
    assert not hasattr(repository, "read_collection_facts")

    with repository._connection() as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert not any(name.startswith("core_objective_") for name in table_names)
    assert not any(name.startswith("core_comparison") for name in table_names)
    assert "core_comparable_results" not in table_names
    assert "core_collection_comparable_results" not in table_names
    assert "core_pairwise_comparison_relations" not in table_names
    assert "core_fact_collection_status" not in table_names
    assert "core_paper_skims" not in table_names
    assert "core_research_objectives" not in table_names


def test_sqlite_core_fact_repository_does_not_own_paper_facts(tmp_path):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    repository._ensure_schema()

    assert not hasattr(repository, "replace_collection_facts")
    assert not hasattr(repository, "replace_collection_document_profiles")

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
