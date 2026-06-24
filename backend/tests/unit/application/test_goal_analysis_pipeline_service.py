from __future__ import annotations

import asyncio

from application.pipeline.goal_analysis.service import GoalAnalysisPipelineService
from domain.core import ConfirmedGoal, ResearchUnderstanding


class FakeConfirmedGoalService:
    def __init__(self) -> None:
        self.statuses: list[str] = []
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
    ) -> ConfirmedGoal:
        assert (collection_id, goal_id) == ("col_1", "goal_1")
        self.statuses.append(status)
        self.goal = ConfirmedGoal.from_mapping(
            {
                **self.goal.to_record(),
                "status": status,
                "analysis_error": analysis_error,
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
    def analyze_confirmed_goal(self, goal: ConfirmedGoal) -> ResearchUnderstanding:
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
