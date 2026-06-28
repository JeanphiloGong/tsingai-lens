from __future__ import annotations

import asyncio

from application.pipeline.goal_analysis.service import GoalAnalysisPipelineService
from domain.core import ConfirmedGoal, ResearchUnderstanding


class FakeConfirmedGoalService:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.progress_updates: list[dict] = []
        self.goal = ConfirmedGoal.from_mapping(
            {
                "collection_id": "col_1",
                "goal_id": "goal_1",
                "question": "How does heat treatment affect strength?",
                "status": "pending",
            }
        )

    def get_goal(self, collection_id: str, goal_id: str) -> ConfirmedGoal:
        assert (collection_id, goal_id) == ("col_1", "goal_1")
        return self.goal

    def update_goal_status(
        self,
        *,
        collection_id: str,
        goal_id: str,
        status: str,
        analysis_error: str | None = None,
        analysis_progress: dict | None = None,
    ) -> ConfirmedGoal:
        assert (collection_id, goal_id) == ("col_1", "goal_1")
        self.statuses.append(status)
        self.goal = ConfirmedGoal.from_mapping(
            {
                **self.goal.to_record(),
                "status": status,
                "analysis_error": analysis_error,
                "analysis_progress": analysis_progress,
            }
        )
        return self.goal

    def update_goal_progress(
        self,
        *,
        collection_id: str,
        goal_id: str,
        analysis_progress: dict,
    ) -> ConfirmedGoal:
        assert (collection_id, goal_id) == ("col_1", "goal_1")
        self.progress_updates.append(analysis_progress)
        self.goal = ConfirmedGoal.from_mapping(
            {
                **self.goal.to_record(),
                "analysis_progress": analysis_progress,
            }
        )
        return self.goal

    def get_goal_understanding(
        self,
        collection_id: str,
        goal_id: str,
    ) -> ResearchUnderstanding | None:
        assert (collection_id, goal_id) == ("col_1", "goal_1")
        return None


class FakeResearchObjectiveService:
    def analyze_confirmed_goal(
        self,
        goal: ConfirmedGoal,
        progress_callback=None,
    ) -> ResearchUnderstanding:
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "objective_evidence_routing_started",
                    "current": 1,
                    "total": 2,
                    "unit": "frames",
                    "active_document_id": "doc_1",
                    "active_document_title": "Heat treatment study",
                }
            )
        return ResearchUnderstanding.from_mapping(
            {
                "state": "ready",
                "scope": {
                    "scope_type": "goal",
                    "collection_id": goal.collection_id,
                    "goal_id": goal.goal_id,
                    "title": goal.question,
                },
                "claims": [
                    {
                        "claim_type": "finding",
                        "statement": "Heat treatment changes strength.",
                        "status": "supported",
                    }
                ],
            }
        )


def test_goal_analysis_pipeline_service_marks_goal_ready():
    confirmed_goal_service = FakeConfirmedGoalService()
    service = GoalAnalysisPipelineService(
        confirmed_goal_service=confirmed_goal_service,
        research_objective_service=FakeResearchObjectiveService(),
    )

    result = asyncio.run(service.run_goal_analysis("col_1", "goal_1"))

    assert confirmed_goal_service.statuses == ["running", "ready"]
    assert result["goal"].status == "ready"
    assert result["understanding"].scope.scope_type == "goal"
    assert result["understanding"].scope.goal_id == "goal_1"
    assert result["pipeline_nodes"]["analyze_goal"]["status"] == "succeeded"
    assert confirmed_goal_service.progress_updates == [
        {
            "phase": "objective_evidence_routing_started",
            "current": 1,
            "total": 2,
            "unit": "frames",
            "active_document_id": "doc_1",
            "active_document_title": "Heat treatment study",
        }
    ]
    assert result["goal"].analysis_progress == {
        "phase": "completed",
        "unit": "steps",
        "message": "Goal analysis is ready.",
    }
