from __future__ import annotations

import pytest

from application.goal.experiment_plan_service import ExperimentPlanService
from infra.persistence.sqlite import (
    SqliteExperimentPlanRepository,
    SqliteGoalSessionRepository,
)


def _write_goal_message(
    repository: SqliteGoalSessionRepository,
    *,
    user_id: str = "expert-a",
    collection_id: str = "col_1",
    goal_id: str = "goal_1",
    message_id: str = "msg_1",
    source_mode: str = "collection_grounded",
    warnings: list[str] | None = None,
    used_evidence_ids: list[str] | None = None,
    content: str = "Run a traceable validation matrix [Source 1].",
) -> None:
    repository.write_session(
        {
            "session_id": "session_1",
            "user_id": user_id,
            "collection_id": collection_id,
            "focused_material_id": None,
            "focused_paper_id": None,
            "focused_objective_id": None,
            "focused_goal_id": goal_id,
            "goal_text": None,
            "goal_brief_json": {},
            "answer_mode": "hybrid",
            "rolling_summary": "",
            "last_evidence_ids": [],
            "last_material_ids": [],
            "last_paper_ids": [],
            "collection_data_version": None,
            "created_at": "2026-07-13T00:00:00+00:00",
            "updated_at": "2026-07-13T00:00:00+00:00",
        }
    )
    repository.write_messages(
        "session_1",
        [
            {
                "message_id": message_id,
                "session_id": "session_1",
                "role": "assistant",
                "content": content,
                "answer": content,
                "source_mode": source_mode,
                "used_evidence_ids": used_evidence_ids or ["ev_1"],
                "warnings": warnings or [],
                "links": {},
                "source_links": [
                    {
                        "kind": "evidence",
                        "label": "Source 1",
                        "href": "/collections/col_1/documents/paper-a?evidence_id=ev_1",
                    }
                ],
                "created_at": "2026-07-13T00:01:00+00:00",
            }
        ],
    )


def test_experiment_plan_service_saves_and_lists_goal_scoped_drafts(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(goal_session_repository)
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
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
                "label": "Stale client label",
                "href": "/collections/col_1/documents/paper-a?evidence_id=ev_1",
            }
        ],
        metadata={"source": "client-supplied", "model": "fake-model"},
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
    assert draft.metadata["source"] == "goal_copilot"
    assert draft.metadata["source_session_id"] == "session_1"
    assert draft.metadata["source_mode"] == "collection_grounded"
    assert draft.metadata["used_evidence_ids"] == ["ev_1"]
    assert draft.metadata["review_gate"] == "training_ready_findings"
    assert [plan.plan_id for plan in plans] == [draft.plan_id]


def test_experiment_plan_service_rejects_unreviewed_goal_copilot_source(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        warnings=["curated_research_findings_empty"],
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="not eligible"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content="Run 25 C and 150 C LPBF 316L builds.",
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_answer_without_source_label(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(
        goal_session_repository,
        content="Run a traceable validation matrix based on the accepted evidence.",
    )
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="does not cite a visible source label"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content="Run 25 C and 150 C LPBF 316L builds.",
            source_message_id="msg_1",
            created_by="expert-a",
            metadata={"source": "goal_copilot"},
        )


def test_experiment_plan_service_rejects_cross_goal_source_message(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(goal_session_repository, goal_id="goal_other")
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="not focused on this goal"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content="Run 25 C and 150 C LPBF 316L builds.",
            source_message_id="msg_1",
            created_by="expert-a",
        )


def test_experiment_plan_service_rejects_source_message_without_user(tmp_path):
    goal_session_repository = SqliteGoalSessionRepository(tmp_path / "lens.sqlite")
    _write_goal_message(goal_session_repository)
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite"),
        goal_session_repository=goal_session_repository,
    )

    with pytest.raises(ValueError, match="authenticated user"):
        service.create_plan(
            collection_id="col_1",
            goal_id="goal_1",
            title="Preheating validation matrix",
            content="Run 25 C and 150 C LPBF 316L builds.",
            source_message_id="msg_1",
        )


def test_experiment_plan_service_allows_manual_draft_without_source_message(tmp_path):
    service = ExperimentPlanService(
        repository=SqliteExperimentPlanRepository(tmp_path / "lens.sqlite")
    )

    draft = service.create_plan(
        collection_id="col_1",
        goal_id="goal_1",
        title="Manual validation plan",
        content="Expert-authored plan without a copilot source.",
        created_by="expert-a",
    )

    assert draft.source_message_id is None
    assert draft.source_links == ()


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
