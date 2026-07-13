from __future__ import annotations

from application.goal.experiment_plan_service import ExperimentPlanService
from infra.persistence.sqlite import SqliteExperimentPlanRepository


def test_experiment_plan_service_saves_and_lists_goal_scoped_drafts(tmp_path):
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite")
    )

    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="Preheating validation matrix",
        content="Run 25 C and 150 C LPBF 316L builds, then compare ductility.",
        source_message_id="msg_1",
        created_by="expert-a",
        source_links=[
            {
                "kind": "evidence",
                "label": "Source 1",
                "href": "/collections/col_1/documents/paper-a?evidence_id=ev_1",
            }
        ],
        metadata={"model": "fake-model"},
    )
    plans = service.list_plans("col_1", "goal_1")

    assert draft.plan_id.startswith("exp_")
    assert draft.status == "draft"
    assert draft.collection_id == "col_1"
    assert draft.goal_id == "goal_1"
    assert draft.title == "Preheating validation matrix"
    assert draft.source_message_id == "msg_1"
    assert draft.created_by == "expert-a"
    assert draft.source_links[0]["label"] == "Source 1"
    assert draft.metadata["model"] == "fake-model"
    assert [plan.plan_id for plan in plans] == [draft.plan_id]


def test_experiment_plan_service_updates_existing_draft(tmp_path):
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite")
    )
    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="Initial draft",
        content="Initial plan.",
        created_by="expert-a",
    )

    updated = service.update_plan(
        collection_id="col_1",
        goal_id="goal_1",
        plan_id=draft.plan_id,
        title="Edited draft",
        content="Edited plan with controls.",
        status="ready_for_review",
    )

    assert updated.plan_id == draft.plan_id
    assert updated.title == "Edited draft"
    assert updated.content == "Edited plan with controls."
    assert updated.status == "ready_for_review"
    assert updated.updated_at >= draft.updated_at
