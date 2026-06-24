from __future__ import annotations

import asyncio

from controllers.core import goal_analysis as goal_analysis_controller
from domain.core import ConfirmedGoal, ResearchUnderstanding


class FakeGoalAnalysisService:
    def __init__(self) -> None:
        self.goal = ConfirmedGoal.from_mapping(
            {
                "collection_id": "col_1",
                "goal_id": "goal_1",
                "question": "How does heat treatment affect strength?",
                "status": "ready",
            }
        )
        self.understanding = ResearchUnderstanding.from_mapping(
            {
                "state": "ready",
                "scope": {
                    "scope_type": "goal",
                    "collection_id": "col_1",
                    "goal_id": "goal_1",
                    "title": "How does heat treatment affect strength?",
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

    async def run_goal_analysis(self, collection_id: str, goal_id: str) -> dict:
        assert (collection_id, goal_id) == ("col_1", "goal_1")
        return {
            "goal": self.goal,
            "understanding": self.understanding,
            "pipeline_nodes": {"analyze_goal": {"status": "succeeded"}},
            "errors": [],
            "warnings": [],
        }

    def get_goal_analysis(self, collection_id: str, goal_id: str) -> dict:
        assert (collection_id, goal_id) == ("col_1", "goal_1")
        return {
            "goal": self.goal,
            "understanding": self.understanding,
            "pipeline_nodes": {},
            "errors": [],
            "warnings": [],
        }


def test_goal_analysis_route_runs_goal_analysis(monkeypatch):
    monkeypatch.setattr(
        goal_analysis_controller,
        "goal_analysis_service",
        FakeGoalAnalysisService(),
    )

    response = asyncio.run(
        goal_analysis_controller.run_confirmed_goal_analysis("col_1", "goal_1")
    )

    assert response.goal.goal_id == "goal_1"
    assert response.goal.status == "ready"
    assert response.understanding is not None
    assert response.understanding.scope.scope_type == "goal"
    assert response.understanding.scope.goal_id == "goal_1"


def test_goal_analysis_route_reads_goal_analysis(monkeypatch):
    monkeypatch.setattr(
        goal_analysis_controller,
        "goal_analysis_service",
        FakeGoalAnalysisService(),
    )

    response = asyncio.run(
        goal_analysis_controller.get_confirmed_goal_analysis("col_1", "goal_1")
    )

    assert response.goal.goal_id == "goal_1"
    assert response.understanding is not None
    assert response.understanding.claims[0].statement == (
        "Heat treatment changes strength."
    )
