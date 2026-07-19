from __future__ import annotations

from domain.core import ConfirmedGoal
from infra.persistence.sqlite import SqliteConfirmedGoalRepository


def test_sqlite_confirmed_goal_repository_owns_only_goal_state(tmp_path):
    repository = SqliteConfirmedGoalRepository(tmp_path / "lens.sqlite")

    assert not hasattr(repository, "read_research_understanding")
    assert not hasattr(repository, "replace_collection_facts")
    assert not hasattr(repository, "read_collection_facts")


def test_sqlite_confirmed_goal_repository_round_trips_goals(tmp_path):
    repository = SqliteConfirmedGoalRepository(tmp_path / "lens.sqlite")
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
            "analysis_progress": {"phase": "queued", "unit": "steps"},
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
