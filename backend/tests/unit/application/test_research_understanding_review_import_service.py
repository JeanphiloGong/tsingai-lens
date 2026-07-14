from __future__ import annotations

import pytest

from application.evaluation.research_understanding_review_import_service import (
    ResearchUnderstandingReviewImportService,
)


class FakeFeedbackService:
    def __init__(self) -> None:
        self.feedback: list[dict] = []
        self.curations: list[dict] = []

    def record_feedback(self, **kwargs):  # noqa: ANN003
        self.feedback.append(kwargs)
        return kwargs

    def record_curation(self, **kwargs):  # noqa: ANN003
        self.curations.append(kwargs)
        return kwargs

    def export_dataset(self, **kwargs):  # noqa: ANN003
        return {
            "collection_id": kwargs["collection_id"],
            "scope_type": kwargs["scope_type"],
            "scope_id": kwargs["scope_id"],
            "item_count": 2,
            "quality_summary": {
                "training_ready_sample_count": 1,
                "training_message_sample_count": 1,
                "review_candidate_sample_count": 1,
                "rejected_count": 0,
            },
            "items": [
                {
                    "finding_id": "finding-accept",
                    "claim_id": "claim-1",
                    "dataset_use_status": "training_ready",
                    "training_messages": [
                        {"role": "user", "content": "Evidence text"},
                        {"role": "assistant", "content": "Finding text"},
                    ],
                    "training_evidence_refs": [{"evidence_ref_id": "ev-1"}],
                    "expert_target": {
                        "statement": "Preheating increases ductility.",
                        "variables": ["preheating"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                    },
                },
                {
                    "finding_id": "finding-correct",
                    "claim_id": "claim-2",
                    "dataset_use_status": "review_candidate",
                    "protocol_readiness": {
                        "status": "ready_after_review",
                        "ready_after_review": True,
                    },
                    "training_evidence_refs": [
                        {
                            "evidence_ref_id": "ev-2",
                            "quote": "Preheating increased ductility by 14%.",
                        }
                    ],
                    "expert_target": {
                        "statement": "Preheating increases ductility by 14%.",
                        "variables": ["preheating"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                    },
                },
            ],
        }


def _row(**overrides):
    row = {
        "collection_id": "col-1",
        "goal_id": "goal-1",
        "finding_id": "finding-accept",
        "claim_id": "claim-1",
        "action": "accept",
        "statement": "Preheating increases ductility.",
        "recommended_action_code": "",
        "review_reasons": [],
    }
    row.update(overrides)
    return row


def test_review_import_service_writes_feedback_and_curation():
    feedback_service = FakeFeedbackService()
    service = ResearchUnderstandingReviewImportService(feedback_service)

    summary = service.import_rows(
        rows=[
            _row(action="accept"),
            _row(
                action="correct",
                finding_id="finding-correct",
                claim_id="claim-2",
                suggested_target={
                    "statement": "Preheating increases ductility by 14%.",
                    "variables": ["preheating"],
                    "outcomes": ["ductility"],
                    "direction": "increase",
                    "evidence_ref_ids": ["ev-2"],
                },
            ),
            _row(action="skip", finding_id="finding-skip"),
        ],
        reviewer="materials-expert@example.com",
    )

    assert summary["status"] == "pass"
    assert summary["written_count"] == 2
    assert summary["counts"] == {"accept": 1, "correct": 1, "skip": 1}
    assert summary["review_progress"]["ready_to_write"] is True
    assert summary["decision_progress_by_goal"] == [
        {
            "collection_id": "col-1",
            "goal_id": "goal-1",
            "total_rows": 3,
            "actionable_count": 2,
            "skipped_count": 1,
            "accept_count": 1,
            "reject_count": 0,
            "correct_count": 1,
            "next_review_finding_id": "finding-skip",
        }
    ]
    assert feedback_service.feedback == [
        {
            "collection_id": "col-1",
            "scope_type": "goal",
            "scope_id": "goal-1",
            "finding_id": "finding-accept",
            "claim_id": "claim-1",
            "review_status": "correct",
            "issue_type": "none",
            "note": "Accepted from expert review JSONL.",
            "reviewer": "materials-expert@example.com",
        }
    ]
    assert feedback_service.curations[0]["finding_id"] == "finding-correct"
    assert feedback_service.curations[0]["curated_evidence_ref_ids"] == ["ev-2"]


def test_review_import_service_blocks_unreviewed_template_when_strict():
    service = ResearchUnderstandingReviewImportService(FakeFeedbackService())

    summary = service.import_rows(
        rows=[_row(action="skip")],
        reviewer="materials-expert@example.com",
        dry_run=True,
        fail_on_warnings=True,
    )

    assert summary["status"] == "fail"
    assert summary["review_progress"] == {
        "actionable_count": 0,
        "skipped_count": 1,
        "needs_review_count": 1,
        "ready_to_write": False,
        "next_steps": [
            "change at least one reviewed row from skip to accept, reject, or correct",
            "leave unchecked rows as skip or review them later",
        ],
    }
    assert summary["decision_progress_by_goal"] == [
        {
            "collection_id": "col-1",
            "goal_id": "goal-1",
            "total_rows": 1,
            "actionable_count": 0,
            "skipped_count": 1,
            "accept_count": 0,
            "reject_count": 0,
            "correct_count": 0,
            "next_review_finding_id": "finding-accept",
        }
    ]


def test_review_import_service_dry_run_reports_affected_goal_readiness():
    service = ResearchUnderstandingReviewImportService(FakeFeedbackService())

    summary = service.import_rows(
        rows=[_row(action="accept", finding_id="finding-correct", claim_id="claim-2")],
        reviewer="materials-expert@example.com",
        dry_run=True,
    )

    assert summary["status"] == "pass"
    assert summary["written_count"] == 0
    assert summary["readiness_summary"] == {
        "goal_count": 1,
        "projected_training_ready_goal_count": 1,
        "projected_training_message_goal_count": 1,
        "projected_protocol_ready_goal_count": 1,
        "projected_review_candidate_count": 0,
        "projected_rejected_count": 0,
        "ready_for_training_export": True,
        "ready_for_protocol_drafting": True,
        "goals_still_needing_review_count": 0,
        "goals_missing_training_messages_count": 0,
        "goals_missing_protocol_ready_count": 0,
    }
    assert summary["affected_goals"] == [
        {
            "collection_id": "col-1",
            "goal_id": "goal-1",
            "item_count": 2,
            "training_ready_count": 1,
            "training_message_count": 1,
            "protocol_ready_count": 1,
            "review_candidate_count": 1,
            "rejected_count": 0,
            "next_review_finding_id": "",
            "pending_actionable_count": 1,
            "pending_accept_count": 1,
            "pending_reject_count": 0,
            "pending_correct_count": 0,
            "pending_training_ready_count": 1,
            "pending_rejected_count": 0,
            "pending_review_candidate_resolved_count": 1,
            "projected_training_ready_count": 2,
            "projected_training_message_count": 2,
            "projected_protocol_ready_count": 2,
            "projected_review_candidate_count": 0,
            "projected_rejected_count": 0,
            "readiness_issues": [],
        }
    ]


def test_review_import_service_post_import_reports_current_readiness_not_pending():
    service = ResearchUnderstandingReviewImportService(FakeFeedbackService())

    summary = service.import_rows(
        rows=[_row(action="accept")],
        reviewer="materials-expert@example.com",
    )

    assert summary["status"] == "pass"
    assert summary["written_count"] == 1
    assert summary["affected_goals"] == [
        {
            "collection_id": "col-1",
            "goal_id": "goal-1",
            "item_count": 2,
            "training_ready_count": 1,
            "training_message_count": 1,
            "protocol_ready_count": 1,
            "review_candidate_count": 1,
            "rejected_count": 0,
            "next_review_finding_id": "",
            "pending_actionable_count": 0,
            "pending_accept_count": 0,
            "pending_reject_count": 0,
            "pending_correct_count": 0,
            "pending_training_ready_count": 0,
            "pending_rejected_count": 0,
            "pending_review_candidate_resolved_count": 0,
            "projected_training_ready_count": 1,
            "projected_training_message_count": 1,
            "projected_protocol_ready_count": 1,
            "projected_review_candidate_count": 1,
            "projected_rejected_count": 0,
            "readiness_issues": [],
        }
    ]


def test_review_import_service_blocks_accept_when_acceptance_gate_denies_it():
    service = ResearchUnderstandingReviewImportService(FakeFeedbackService())

    summary = service.import_rows(
        rows=[
            _row(
                action="accept",
                acceptance_gate={
                    "accept_allowed": False,
                    "requires_correction": True,
                    "blocking_missing": [],
                },
            )
        ],
        reviewer="materials-expert@example.com",
        dry_run=True,
    )

    assert summary["status"] == "fail"
    assert summary["written_count"] == 0
    assert summary["errors"][0]["message"] == (
        "accept is blocked by acceptance_gate; use correct or reject"
    )


def test_review_import_service_blocks_accept_when_acceptance_gate_has_blockers():
    service = ResearchUnderstandingReviewImportService(FakeFeedbackService())

    summary = service.import_rows(
        rows=[
            _row(
                action="accept",
                acceptance_gate={
                    "accept_allowed": True,
                    "requires_correction": False,
                    "blocking_missing": [],
                    "accept_blockers": [
                        "verify_table_rows",
                        "table_row_alignment_uncertain",
                    ],
                },
            )
        ],
        reviewer="materials-expert@example.com",
        dry_run=True,
    )

    assert summary["status"] == "fail"
    assert summary["written_count"] == 0
    assert summary["errors"][0]["message"] == (
        "accept is blocked by acceptance_gate.accept_blockers; "
        "use correct or reject for: verify_table_rows, table_row_alignment_uncertain"
    )


def test_review_import_service_rejects_agent_reviewer():
    service = ResearchUnderstandingReviewImportService(FakeFeedbackService())

    with pytest.raises(ValueError, match="human expert"):
        service.import_rows(rows=[_row()], reviewer="agent-reviewer")


def test_review_import_service_imports_human_confirmed_agent_accept():
    feedback_service = FakeFeedbackService()
    service = ResearchUnderstandingReviewImportService(feedback_service)

    summary = service.import_rows(
        rows=[
            _row(
                action="skip",
                acceptance_gate={
                    "accept_allowed": True,
                    "blocking_missing": [],
                },
                agent_review={
                    "reviewer": "agent-materials-review",
                    "recommendation": "accept",
                    "note": "Evidence supports the finding.",
                    "human_confirmed": True,
                },
            )
        ],
        reviewer="materials-expert@example.com",
    )

    assert summary["status"] == "pass"
    assert summary["written_count"] == 1
    assert summary["counts"] == {"accept": 1}
    assert feedback_service.feedback[0]["review_status"] == "correct"
    assert feedback_service.feedback[0]["reviewer"] == "materials-expert@example.com"
    assert feedback_service.feedback[0]["note"] == "Evidence supports the finding."


def test_review_import_service_blocks_human_confirmed_agent_accept_with_gate_gaps():
    service = ResearchUnderstandingReviewImportService(FakeFeedbackService())

    summary = service.import_rows(
        rows=[
            _row(
                action="skip",
                acceptance_gate={
                    "accept_allowed": False,
                    "blocking_missing": ["variables"],
                },
                agent_review={
                    "reviewer": "agent-materials-review",
                    "recommendation": "accept",
                    "note": "Looks right.",
                    "human_confirmed": True,
                },
            )
        ],
        reviewer="materials-expert@example.com",
    )

    assert summary["status"] == "fail"
    assert summary["errors"][0]["message"] == (
        "line 1: confirmed accept is blocked by acceptance_gate"
    )


def test_review_import_service_imports_human_confirmed_agent_correction():
    feedback_service = FakeFeedbackService()
    service = ResearchUnderstandingReviewImportService(feedback_service)

    summary = service.import_rows(
        rows=[
            _row(
                action="skip",
                finding_id="finding-correct",
                claim_id="claim-2",
                agent_review={
                    "reviewer": "agent-materials-review",
                    "recommendation": "correct",
                    "note": "Use the narrower finding.",
                    "human_confirmed": True,
                    "suggested_target": {
                        "statement": "Preheating increases ductility by 14%.",
                        "variables": ["preheating"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                        "evidence_ref_ids": ["ev-2"],
                    },
                },
            )
        ],
        reviewer="materials-expert@example.com",
    )

    assert summary["status"] == "pass"
    assert summary["written_count"] == 1
    assert summary["counts"] == {"correct": 1}
    assert feedback_service.curations[0]["curated_statement"] == (
        "Preheating increases ductility by 14%."
    )
    assert feedback_service.curations[0]["curated_evidence_ref_ids"] == ["ev-2"]
    assert feedback_service.curations[0]["note"] == "Use the narrower finding."
