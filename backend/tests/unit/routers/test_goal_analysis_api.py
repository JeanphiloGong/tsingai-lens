from __future__ import annotations

import asyncio

from controllers.core import goal_analysis as goal_analysis_controller
from domain.core import ConfirmedGoal, ResearchUnderstanding


class FakeGoalAnalysisService:
    def __init__(self) -> None:
        self.started = False
        self.ran = False
        self.goal = ConfirmedGoal.from_mapping(
            {
                "collection_id": "col_1",
                "goal_id": "goal_1",
                "question": "How does heat treatment affect strength?",
                "status": "running",
                "analysis_progress": {
                    "phase": "queued",
                    "unit": "steps",
                    "message": "Goal analysis is queued.",
                },
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
        self.ran = True
        return {
            "goal": ConfirmedGoal.from_mapping(
                {
                    **self.goal.to_record(),
                    "status": "ready",
                    "analysis_progress": {
                        "phase": "completed",
                        "unit": "steps",
                        "message": "Goal analysis is ready.",
                    },
                }
            ),
            "understanding": self.understanding,
            "pipeline_nodes": {"analyze_goal": {"status": "succeeded"}},
            "errors": [],
            "warnings": [],
        }

    def start_goal_analysis(self, collection_id: str, goal_id: str) -> dict:
        assert (collection_id, goal_id) == ("col_1", "goal_1")
        self.started = True
        return {
            "goal": self.goal,
            "understanding": None,
            "pipeline_nodes": {},
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


class ImmediateFuture:
    def __init__(self, result):
        self._result = result

    def add_done_callback(self, callback):
        callback(self)

    def result(self):
        return self._result


class ImmediateExecutor:
    def __init__(self) -> None:
        self.submitted: list[tuple] = []

    def submit(self, function, *args):
        self.submitted.append((function, args))
        return ImmediateFuture(function(*args))


def test_goal_analysis_route_runs_goal_analysis(monkeypatch):
    service = FakeGoalAnalysisService()
    executor = ImmediateExecutor()

    def run_blocking(collection_id: str, goal_id: str) -> dict:
        assert (collection_id, goal_id) == ("col_1", "goal_1")
        service.ran = True
        return {}

    monkeypatch.setattr(
        goal_analysis_controller,
        "goal_analysis_service",
        service,
    )
    monkeypatch.setattr(
        goal_analysis_controller,
        "_goal_analysis_executor",
        executor,
    )
    monkeypatch.setattr(
        goal_analysis_controller,
        "_run_goal_analysis_blocking",
        run_blocking,
    )
    goal_analysis_controller._active_goal_analysis_jobs.clear()

    response = asyncio.run(
        goal_analysis_controller.run_confirmed_goal_analysis("col_1", "goal_1")
    )

    assert response.goal.goal_id == "goal_1"
    assert response.goal.status == "running"
    assert response.goal.analysis_progress is not None
    assert response.goal.analysis_progress["phase"] == "queued"
    assert response.understanding is None
    assert service.started is True
    assert service.ran is True
    assert len(executor.submitted) == 1


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
