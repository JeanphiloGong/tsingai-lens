from __future__ import annotations

from application.evaluation import research_understanding_feedback_service as service


def test_dataset_quality_summary_breaks_down_errors_by_research_dimensions():
    summary = service._dataset_quality_summary(
        [
            {
                "label_status": "gold",
                "dataset_use_status": "training_ready",
                "expert_target": {"source": "curation"},
                "system_prediction": {
                    "variables": ["preheating"],
                    "outcomes": ["ductility"],
                    "direction": "increase",
                },
                "feedback_refs": [
                    {
                        "issue_type": "wrong_direction",
                        "review_status": "incorrect",
                    }
                ],
                "evidence_refs": [
                    {
                        "evidence_role": "direct_result",
                        "traceability_status": "resolved",
                        "quote": "Preheating increased ductility by 14%.",
                    }
                ],
                "context_refs": [{"context_id": "ctx-1"}],
            },
            {
                "label_status": "silver",
                "dataset_use_status": "review_candidate",
                "expert_target": {},
                "system_prediction": {
                    "variables": ["scan speed"],
                    "outcomes": ["density"],
                    "direction": "condition-dependent",
                    "review_reasons": ["table_row_needs_expert_review"],
                    "warnings": ["table_row_alignment_uncertain"],
                },
                "feedback_refs": [],
                "evidence_refs": [
                    {
                        "evidence_role": "table_row",
                        "traceability_status": "resolved",
                        "quote": "Relevant table rows.",
                    }
                ],
                "context_refs": [{"context_id": "ctx-2"}],
            },
        ]
    )

    assert summary["optimization_breakdown"]["by_variable"]["preheating"] == {
        "issue_type": {"wrong_direction": 1},
        "error_category": {"direction_error": 1},
        "review_candidate_reason": {},
        "system_warning": {},
    }
    assert summary["optimization_breakdown"]["by_outcome"]["density"] == {
        "issue_type": {"unreviewed": 1},
        "error_category": {"unreviewed": 1},
        "review_candidate_reason": {"table_row_needs_expert_review": 1},
        "system_warning": {"table_row_alignment_uncertain": 1},
    }
    assert summary["optimization_breakdown"]["by_direction"][
        "condition-dependent"
    ]["review_candidate_reason"] == {"table_row_needs_expert_review": 1}
    assert summary["optimization_breakdown"]["by_evidence_role"]["table_row"][
        "system_warning"
    ] == {"table_row_alignment_uncertain": 1}
    assert summary["top_variable_issue_types"] == [
        {"name": "preheating", "metric": "wrong_direction", "count": 1}
    ]
    assert summary["top_evidence_role_review_reasons"] == [
        {"name": "table_row", "metric": "table_row_needs_expert_review", "count": 1}
    ]
