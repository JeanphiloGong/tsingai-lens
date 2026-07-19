from __future__ import annotations

from types import SimpleNamespace

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

    def run_blocking(service_argument, collection_id: str, goal_id: str) -> dict:
        assert service_argument is service
        assert (collection_id, goal_id) == ("col_1", "goal_1")
        service.ran = True
        return {}

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
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(goal_analysis_service=service))
    )

    response = goal_analysis_controller.run_confirmed_goal_analysis(
        "col_1",
        "goal_1",
        request,
    )

    assert response.goal.goal_id == "goal_1"
    assert response.goal.status == "running"
    assert response.goal.analysis_progress is not None
    assert response.goal.analysis_progress["phase"] == "queued"
    assert response.understanding is None
    assert service.started is True
    assert service.ran is True
    assert len(executor.submitted) == 1


def test_goal_analysis_route_reads_goal_analysis():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(goal_analysis_service=FakeGoalAnalysisService())
        )
    )

    response = goal_analysis_controller.get_confirmed_goal_analysis(
        "col_1",
        "goal_1",
        request,
    )

    assert response.goal.goal_id == "goal_1"
    assert response.understanding is not None
    assert response.understanding.claims[0].statement == (
        "Heat treatment changes strength."
    )


def test_goal_analysis_response_serializes_service_projected_presentation():
    payload = {
        "goal": {
            "collection_id": "col_1",
            "goal_id": "goal_1",
            "question": "How does scan speed affect density?",
            "source_type": "user_input",
            "status": "ready",
        },
        "understanding": {
            "schema_version": "research_understanding.v1",
            "state": "ready",
            "scope": {
                "scope_type": "goal",
                "collection_id": "col_1",
                "goal_id": "goal_1",
                "title": "How does scan speed affect density?",
            },
            "claims": [],
            "relations": [],
            "evidence_refs": [],
            "contexts": [],
            "warnings": [],
            "summary": {
                "claim_count": 0,
                "relation_count": 0,
                "evidence_ref_count": 0,
                "context_count": 0,
            },
            "presentation": {
                "summary": {
                    "title": "How does scan speed affect density?",
                    "material_scope": [],
                    "variable_axes": ["scan speed"],
                    "property_scope": ["density"],
                    "claim_count": 0,
                    "relation_count": 0,
                    "evidence_count": 0,
                    "context_count": 0,
                    "review_queue_count": 1,
                    "primary_finding_count": 0,
                    "review_queue_finding_count": 1,
                },
                "effects": [],
                "findings": [],
                "primary_findings": [],
                "review_queue_findings": [
                    {
                        "finding_id": "finding-review-1",
                        "claim_id": "claim-review-1",
                        "title": "scan speed -> density",
                        "statement": "Service-projected review candidate.",
                        "variables": ["scan speed"],
                        "mediators": [],
                        "outcomes": ["density"],
                        "direction": "changes",
                        "relation_chain": [],
                        "scope_summary": "316L stainless steel",
                        "support_grade": "partial",
                        "review_status": "needs_review",
                        "confidence": 0.5,
                        "paper_count": 1,
                        "evidence_count": 0,
                        "evidence_ref_ids": [],
                        "context_ids": [],
                        "relation_ids": [],
                        "evidence_bundle": {
                            "direct_result": [],
                            "mechanism": [],
                            "condition_context": [],
                            "conflict": [],
                            "background": [],
                            "uncategorized": [],
                            "noise": [],
                        },
                        "comparison_summary": None,
                        "expert_use_status": "review_candidate",
                        "dataset_use_status": "review_candidate",
                        "generalization_status": "paper_level_only",
                        "generalization_note": "Service projection should be serialized.",
                        "evidence_gap_summary": "Needs review.",
                        "upgrade_actions": [],
                        "review_reasons": ["needs_expert_review"],
                        "warnings": [],
                    }
                ],
                "evidence_items": [],
                "context_summaries": [],
            },
        },
        "pipeline_nodes": {},
        "errors": [],
        "warnings": [],
    }

    response = goal_analysis_controller._analysis_response("col_1", payload)

    review_findings = response.understanding.presentation.review_queue_findings
    assert len(review_findings) == 1
    assert review_findings[0].statement == "Service-projected review candidate."


def test_goal_analysis_response_preserves_presentation_evidence_source_text():
    response = goal_analysis_controller.GoalAnalysisResponse.model_validate(
        {
            "collection_id": "col_1",
            "goal": {
                "collection_id": "col_1",
                "goal_id": "goal_1",
                "question": "How does preheating affect ductility?",
                "source_type": "user_input",
                "status": "ready",
            },
            "understanding": {
                "schema_version": "research_understanding.v1",
                "state": "ready",
                "scope": {
                    "scope_type": "goal",
                    "collection_id": "col_1",
                    "goal_id": "goal_1",
                    "title": "How does preheating affect ductility?",
                },
                "claims": [],
                "relations": [],
                "evidence_refs": [],
                "contexts": [],
                "warnings": [],
                "summary": {
                    "claim_count": 0,
                    "relation_count": 0,
                    "evidence_ref_count": 1,
                    "context_count": 0,
                },
                "presentation": {
                    "summary": {
                        "title": "How does preheating affect ductility?",
                        "material_scope": [],
                        "variable_axes": [],
                        "property_scope": [],
                        "claim_count": 0,
                        "relation_count": 0,
                        "evidence_count": 1,
                        "context_count": 0,
                        "review_queue_count": 0,
                        "primary_finding_count": 0,
                        "review_queue_finding_count": 0,
                    },
                    "effects": [],
                    "findings": [],
                    "primary_findings": [],
                    "review_queue_findings": [],
                    "evidence_items": [
                        {
                            "evidence_ref_id": "ev_table_2",
                            "document_id": "doc_1",
                            "title": "P002 Table 2 / p. 8",
                            "source_label": "P002",
                            "source_kind": "table",
                            "source_ref": "tbl_doc_1_2_table_2",
                            "block_type": None,
                            "heading_path": "Results",
                            "page": "8",
                            "quote": (
                                "Table 2. Columns: Build platform conditions | "
                                "El% Rows: Non-preheated | 72 / Preheated | 82"
                            ),
                            "source_text": (
                                "Table 2. Columns: Build platform conditions | "
                                "El% Rows: Non-preheated | 72 / Preheated | 82"
                            ),
                            "value_summary": "",
                            "traceability_status": "resolved",
                            "evidence_role": "direct_support",
                            "confidence": 0.91,
                            "href": (
                                "/collections/col_1/documents/doc_1"
                                "?view=parsed-paper&page=8"
                                "&source_ref=tbl_doc_1_2_table_2"
                            ),
                        }
                    ],
                    "context_summaries": [],
                },
            },
            "pipeline_nodes": {},
            "errors": [],
            "warnings": [],
        }
    )

    evidence = response.understanding.presentation.evidence_items[0]
    assert evidence.source_ref == "tbl_doc_1_2_table_2"
    assert evidence.heading_path == "Results"
    assert evidence.source_text is not None
    assert "Preheated | 82" in evidence.source_text
