from __future__ import annotations

import asyncio

from application.pipeline.goal_analysis.service import GoalAnalysisPipelineService
from domain.core import ConfirmedGoal, ResearchUnderstanding


class FakeConfirmedGoalService:
    def __init__(self, understanding: ResearchUnderstanding | None = None) -> None:
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
        self.understanding = understanding

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
        return self.understanding


class FakeResearchObjectiveService:
    def __init__(self, understanding_payload: dict | None = None) -> None:
        self.force_rebuild_values: list[bool] = []
        self.understanding_payload = understanding_payload

    def analyze_confirmed_goal(
        self,
        goal: ConfirmedGoal,
        progress_callback=None,
        force_rebuild: bool = False,
    ) -> ResearchUnderstanding:
        self.force_rebuild_values.append(force_rebuild)
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
            self.understanding_payload
            or {
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
                "presentation": {
                    "primary_findings": [
                        {
                            "finding_id": "finding_heat_strength",
                            "title": "heat treatment -> strength",
                            "statement": "Heat treatment changes strength.",
                        }
                    ]
                },
            }
        )


class FakeResearchUnderstandingService:
    def with_presentation(self, understanding):
        return understanding.to_record() if hasattr(understanding, "to_record") else understanding


def test_goal_analysis_pipeline_service_marks_goal_ready():
    confirmed_goal_service = FakeConfirmedGoalService()
    research_objective_service = FakeResearchObjectiveService()
    service = GoalAnalysisPipelineService(
        confirmed_goal_service=confirmed_goal_service,
        research_objective_service=research_objective_service,
        research_understanding_service=FakeResearchUnderstandingService(),
    )

    result = asyncio.run(service.run_goal_analysis("col_1", "goal_1"))

    assert confirmed_goal_service.statuses == ["running", "ready"]
    assert result["goal"].status == "ready"
    assert result["understanding"].scope.scope_type == "goal"
    assert result["understanding"].scope.goal_id == "goal_1"
    assert result["pipeline_nodes"]["analyze_goal"]["status"] == "succeeded"
    assert research_objective_service.force_rebuild_values == [True]
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


def test_goal_analysis_pipeline_service_fails_without_primary_findings():
    confirmed_goal_service = FakeConfirmedGoalService()
    research_objective_service = FakeResearchObjectiveService(
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
                    "claim_type": "measurement",
                    "statement": "Strength is reported as 450 MPa.",
                    "status": "supported",
                }
            ],
            "presentation": {
                "findings": [],
                "primary_findings": [],
                "review_queue_findings": [],
            },
        }
    )
    service = GoalAnalysisPipelineService(
        confirmed_goal_service=confirmed_goal_service,
        research_objective_service=research_objective_service,
        research_understanding_service=FakeResearchUnderstandingService(),
    )

    result = asyncio.run(service.run_goal_analysis("col_1", "goal_1"))

    assert confirmed_goal_service.statuses == ["running", "failed"]
    assert result["goal"].status == "failed"
    assert result["errors"] == [
        "finalize_goal: goal analysis produced no research findings"
    ]
    assert result["goal"].analysis_progress == {
        "phase": "failed",
        "unit": "steps",
        "message": "Goal analysis failed.",
    }


def test_goal_analysis_pipeline_service_marks_review_only_findings_ready():
    confirmed_goal_service = FakeConfirmedGoalService()
    research_objective_service = FakeResearchObjectiveService(
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
                    "statement": "Heat treatment may change strength.",
                    "status": "supported",
                }
            ],
            "presentation": {
                "findings": [],
                "primary_findings": [],
                "review_queue_findings": [
                    {
                        "finding_id": "finding_review_heat_strength",
                        "title": "heat treatment -> strength",
                        "statement": "Heat treatment may change strength.",
                    }
                ],
            },
        }
    )
    service = GoalAnalysisPipelineService(
        confirmed_goal_service=confirmed_goal_service,
        research_objective_service=research_objective_service,
        research_understanding_service=FakeResearchUnderstandingService(),
    )

    result = asyncio.run(service.run_goal_analysis("col_1", "goal_1"))

    assert confirmed_goal_service.statuses == ["running", "ready"]
    assert result["goal"].status == "ready"
    assert result["errors"] == []
    assert result["warnings"] == [
        "finalize_goal: goal analysis produced review candidates but no primary research findings"
    ]
    assert result["goal"].analysis_progress == {
        "phase": "completed",
        "unit": "steps",
        "message": "Goal analysis is ready.",
    }


def test_goal_analysis_pipeline_service_flags_stale_ready_goal_without_findings():
    confirmed_goal_service = FakeConfirmedGoalService(
        ResearchUnderstanding.from_mapping(
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
                        "claim_type": "measurement",
                        "statement": "Strength is reported as 450 MPa.",
                        "status": "supported",
                    }
                ],
                "presentation": {
                    "findings": [],
                    "primary_findings": [],
                    "review_queue_findings": [],
                },
            }
        )
    )
    confirmed_goal_service.goal = ConfirmedGoal.from_mapping(
        {
            **confirmed_goal_service.goal.to_record(),
            "status": "ready",
        }
    )
    service = GoalAnalysisPipelineService(
        confirmed_goal_service=confirmed_goal_service,
        research_objective_service=FakeResearchObjectiveService(),
        research_understanding_service=FakeResearchUnderstandingService(),
    )

    result = service.get_goal_analysis("col_1", "goal_1")

    assert result["goal"].status == "ready"
    assert result["errors"] == [
        "goal analysis produced no research findings"
    ]


def test_goal_analysis_pipeline_service_warns_for_stale_ready_goal_with_review_only_findings():
    confirmed_goal_service = FakeConfirmedGoalService(
        ResearchUnderstanding.from_mapping(
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
                        "statement": "Heat treatment may change strength.",
                        "status": "supported",
                    }
                ],
                "presentation": {
                    "findings": [],
                    "primary_findings": [],
                    "review_queue_findings": [
                        {
                            "finding_id": "finding_review_heat_strength",
                            "title": "heat treatment -> strength",
                            "statement": "Heat treatment may change strength.",
                        }
                    ],
                },
            }
        )
    )
    confirmed_goal_service.goal = ConfirmedGoal.from_mapping(
        {
            **confirmed_goal_service.goal.to_record(),
            "status": "ready",
        }
    )
    service = GoalAnalysisPipelineService(
        confirmed_goal_service=confirmed_goal_service,
        research_objective_service=FakeResearchObjectiveService(),
        research_understanding_service=FakeResearchUnderstandingService(),
    )

    result = service.get_goal_analysis("col_1", "goal_1")

    assert result["goal"].status == "ready"
    assert result["errors"] == []
    assert result["warnings"] == [
        "goal analysis produced review candidates but no primary research findings"
    ]
