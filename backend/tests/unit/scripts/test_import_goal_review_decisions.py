from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_import_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "import_goal_review_decisions.py"
    )
    spec = importlib.util.spec_from_file_location(
        "import_goal_review_decisions",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeFeedbackService:
    def __init__(self) -> None:
        self.feedback: list[dict] = []
        self.curations: list[dict] = []
        self.dataset_exports: list[dict] = []

    def record_feedback(self, **kwargs):  # noqa: ANN003
        self.feedback.append(kwargs)
        return kwargs

    def record_curation(self, **kwargs):  # noqa: ANN003
        self.curations.append(kwargs)
        return kwargs

    def export_dataset(self, **kwargs):  # noqa: ANN003
        self.dataset_exports.append(kwargs)
        return {
            "collection_id": kwargs["collection_id"],
            "scope_type": kwargs["scope_type"],
            "scope_id": kwargs["scope_id"],
            "item_count": 4,
            "quality_summary": {
                "training_ready_sample_count": 2,
                "training_message_sample_count": 1,
                "review_candidate_sample_count": 1,
                "rejected_count": 1,
                "next_review_finding_id": "finding-next",
            },
            "items": [
                {
                    "finding_id": "finding-accept",
                    "claim_id": "claim-1",
                    "dataset_use_status": "training_ready",
                    "system_prediction": {
                        "statement": "Preheating increased ductility by 14%.",
                        "variables": ["preheating"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                    },
                    "training_evidence_refs": [{"evidence_ref_id": "ev-1"}],
                },
                {
                    "finding_id": "finding-correct",
                    "claim_id": "claim-1",
                    "dataset_use_status": "training_ready",
                    "expert_target": {
                        "statement": "Preheating increased ductility by 14%.",
                        "variables": ["preheating"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                    },
                    "training_messages": [
                        {"role": "user", "content": "Evidence text"},
                        {
                            "role": "assistant",
                            "content": (
                                '{"statement":"Preheating increased ductility by 14%."}'
                            ),
                        },
                    ],
                    "training_evidence_refs": [{"evidence_ref_id": "ev-1"}],
                },
                {
                    "finding_id": "finding-1",
                    "claim_id": "claim-1",
                    "dataset_use_status": "review_candidate",
                    "protocol_readiness": {
                        "status": "ready_after_review",
                        "ready_after_review": True,
                        "blocking_missing": [],
                    },
                    "system_prediction": {
                        "statement": "Preheating improved ductility.",
                        "variables": ["preheating"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                        "support_grade": "partial",
                    },
                    "training_evidence_refs": [
                        {
                            "evidence_ref_id": "ev-1",
                            "quote": "Preheating increased ductility by 14%.",
                        }
                    ],
                },
                {
                    "finding_id": "finding-reject",
                    "claim_id": "claim-1",
                    "dataset_use_status": "rejected",
                },
            ],
        }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _base_row(**overrides):
    row = {
        "collection_id": "col-1",
        "goal_id": "goal-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
        "statement": "Preheating improves ductility.",
        "variables": ["preheating"],
        "mediators": ["homogenized microstructure"],
        "outcomes": ["ductility"],
        "direction": "increase",
        "scope_summary": "LPBF 316L",
        "support_grade": "partial",
        "evidence": [
            {
                "evidence_ref_id": "ev-1",
                "quote": "Preheating increased ductility by 14%.",
            }
        ],
    }
    row.update(overrides)
    return row


def test_import_review_decisions_writes_feedback_and_curation(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(action="accept", finding_id="finding-accept"),
            _base_row(
                action="reject",
                finding_id="finding-reject",
                issue_type="wrong_direction",
                expert_note="Direction is reversed.",
            ),
            _base_row(
                action="correct",
                finding_id="finding-correct",
                suggested_target={
                    "statement": "Preheating increased ductility by 14%.",
                    "status": "limited",
                    "support_grade": "partial",
                    "review_status": "accepted",
                    "variables": ["preheating"],
                    "mediators": ["homogenized microstructure"],
                    "outcomes": ["ductility"],
                    "direction": "increase",
                    "scope_summary": "LPBF 316L",
                    "evidence_ref_ids": ["ev-1"],
                },
            ),
            _base_row(action="skip", finding_id="finding-skip"),
        ],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        feedback_service=service,
    )

    assert summary == {
        "status": "pass",
        "dry_run": False,
        "total_rows": 4,
        "written_count": 3,
        "skipped_count": 1,
        "counts": {"accept": 1, "correct": 1, "reject": 1, "skip": 1},
        "errors": [],
        "warnings": [],
        "review_progress": {
            "actionable_count": 3,
            "skipped_count": 1,
            "needs_review_count": 1,
            "ready_to_write": True,
            "next_steps": [
                "leave unchecked rows as skip or review them later",
                "rerun dry-run with --fail-on-warnings before import",
            ],
        },
        "decision_progress_by_goal": [
            {
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "total_rows": 4,
                "actionable_count": 3,
                "skipped_count": 1,
                "accept_count": 1,
                "reject_count": 1,
                "correct_count": 1,
                "next_review_finding_id": "finding-skip",
            }
        ],
        "affected_goals": [
            {
                "collection_id": "col-1",
                "goal_id": "goal-1",
                "item_count": 4,
                "training_ready_count": 2,
                "training_message_count": 1,
                "protocol_ready_count": 1,
                "review_candidate_count": 1,
                "rejected_count": 1,
                "next_review_finding_id": "finding-next",
                "readiness_issues": [
                    {
                        "finding_id": "finding-accept",
                        "claim_id": "claim-1",
                        "missing_training_message": ["message_pair"],
                        "missing_protocol_input": ["training_messages"],
                    }
                ],
                "pending_actionable_count": 0,
                "pending_accept_count": 0,
                "pending_reject_count": 0,
                "pending_correct_count": 0,
                "pending_training_ready_count": 0,
                "pending_rejected_count": 0,
                "pending_review_candidate_resolved_count": 0,
                "projected_training_ready_count": 2,
                "projected_training_message_count": 1,
                "projected_protocol_ready_count": 1,
                "projected_review_candidate_count": 1,
                "projected_rejected_count": 1,
            }
        ],
        "readiness_summary": {
            "goal_count": 1,
            "projected_training_ready_goal_count": 1,
            "projected_training_message_goal_count": 1,
            "projected_protocol_ready_goal_count": 1,
            "projected_review_candidate_count": 1,
            "projected_rejected_count": 1,
            "ready_for_training_export": True,
            "ready_for_protocol_drafting": True,
            "goals_still_needing_review_count": 1,
            "goals_missing_training_messages_count": 0,
            "goals_missing_protocol_ready_count": 0,
        },
    }
    assert service.dataset_exports == [
        {
            "collection_id": "col-1",
            "scope_type": "goal",
            "scope_id": "goal-1",
        },
        {
            "collection_id": "col-1",
            "scope_type": "goal",
            "scope_id": "goal-1",
        }
    ]
    assert service.feedback == [
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
        },
        {
            "collection_id": "col-1",
            "scope_type": "goal",
            "scope_id": "goal-1",
            "finding_id": "finding-reject",
            "claim_id": "claim-1",
            "review_status": "incorrect",
            "issue_type": "wrong_direction",
            "note": "Direction is reversed.",
            "reviewer": "materials-expert@example.com",
        },
    ]
    assert service.curations == [
        {
            "collection_id": "col-1",
            "scope_type": "goal",
            "scope_id": "goal-1",
            "finding_id": "finding-correct",
            "claim_id": "claim-1",
            "curated_claim_type": "finding",
            "curated_status": "limited",
            "curated_statement": "Preheating increased ductility by 14%.",
            "curated_support_grade": "partial",
            "curated_review_status": "accepted",
            "curated_variables": ["preheating"],
            "curated_mediators": ["homogenized microstructure"],
            "curated_outcomes": ["ductility"],
            "curated_direction": "increase",
            "curated_scope_summary": "LPBF 316L",
            "curated_evidence_ref_ids": ["ev-1"],
            "curated_context_ids": [],
            "note": "Corrected from expert review JSONL.",
            "reviewer": "materials-expert@example.com",
        }
    ]


def test_import_review_decisions_dry_run_does_not_write(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(input_path, [_base_row(action="accept")])

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        feedback_service=service,
    )

    assert summary["status"] == "pass"
    assert summary["written_count"] == 0
    assert summary["counts"] == {"accept": 1}
    assert summary["warnings"] == []
    assert summary["review_progress"] == {
        "actionable_count": 1,
        "skipped_count": 0,
        "needs_review_count": 0,
        "ready_to_write": True,
        "next_steps": ["rerun dry-run with --fail-on-warnings before import"],
    }
    assert summary["affected_goals"] == [
        {
            "collection_id": "col-1",
            "goal_id": "goal-1",
            "item_count": 4,
            "training_ready_count": 2,
            "training_message_count": 1,
            "protocol_ready_count": 1,
            "review_candidate_count": 1,
            "rejected_count": 1,
            "next_review_finding_id": "finding-next",
            "readiness_issues": [
                {
                    "finding_id": "finding-accept",
                    "claim_id": "claim-1",
                    "missing_training_message": ["message_pair"],
                    "missing_protocol_input": ["training_messages"],
                }
            ],
            "pending_actionable_count": 1,
            "pending_accept_count": 1,
            "pending_reject_count": 0,
            "pending_correct_count": 0,
            "pending_training_ready_count": 1,
            "pending_rejected_count": 0,
            "pending_review_candidate_resolved_count": 1,
            "projected_training_ready_count": 3,
            "projected_training_message_count": 2,
            "projected_protocol_ready_count": 2,
            "projected_review_candidate_count": 0,
            "projected_rejected_count": 1,
        }
    ]
    assert summary["readiness_summary"] == {
        "goal_count": 1,
        "projected_training_ready_goal_count": 1,
        "projected_training_message_goal_count": 1,
        "projected_protocol_ready_goal_count": 1,
        "projected_review_candidate_count": 0,
        "projected_rejected_count": 1,
        "ready_for_training_export": True,
        "ready_for_protocol_drafting": True,
        "goals_still_needing_review_count": 0,
        "goals_missing_training_messages_count": 0,
        "goals_missing_protocol_ready_count": 0,
    }
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_renders_text_summary(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(action="accept", finding_id="finding-1"),
            _base_row(action="skip", finding_id="finding-skip"),
        ],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        feedback_service=service,
    )
    text = module.render_text_summary(summary)

    assert "Review decision import: pass (dry-run)" in text
    assert "Rows: total=2 written=0 skipped=1" in text
    assert "Decisions: accept=1, skip=1" in text
    assert "Review progress: actionable=1 needs_review=1 ready_to_write=True" in text
    assert "- col-1/goal-1" in text
    assert (
        "now: training_ready=2 training_messages=1 protocol_ready=1 "
        "review_candidates=1 rejected=1"
    ) in text
    assert "pending: accept=1 correct=0 reject=0" in text
    assert (
        "after import: training_ready=3 training_messages=2 protocol_ready=2 "
        "review_candidates=0 rejected=1"
    ) in text
    assert "Readiness after import:" in text
    assert "goals=1 training_ready_goals=1 message_ready_goals=1 protocol_ready_goals=1" in text
    assert "ready_for_training_export=True ready_for_protocol_drafting=True" in text
    assert "finding-accept: training=message_pair; protocol=training_messages" in text


def test_import_review_decisions_warns_when_all_rows_are_skipped(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(input_path, [_base_row(action="skip"), _base_row(action="skip")])

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        feedback_service=service,
    )

    assert summary["status"] == "pass"
    assert summary["written_count"] == 0
    assert summary["counts"] == {"skip": 2}
    assert summary["warnings"] == [
        {
            "line": 0,
            "action": "skip",
            "finding_id": "",
            "message": (
                "no_actionable_decisions: all rows are skip; no expert labels "
                "will be written"
            ),
        }
    ]
    assert summary["review_progress"] == {
        "actionable_count": 0,
        "skipped_count": 2,
        "needs_review_count": 2,
        "ready_to_write": False,
        "next_steps": [
            "change at least one reviewed row from skip to accept, reject, or correct",
            "leave unchecked rows as skip or review them later",
        ],
    }
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_fail_on_warnings_rejects_all_skip_import(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(input_path, [_base_row(action="skip")])

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        fail_on_warnings=True,
        feedback_service=service,
    )

    assert summary["status"] == "fail"
    assert summary["written_count"] == 0
    assert summary["warnings"] == [
        {
            "line": 0,
            "action": "skip",
            "finding_id": "",
            "message": (
                "no_actionable_decisions: all rows are skip; no expert labels "
                "will be written"
            ),
        }
    ]
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
    assert [error["message"] for error in summary["errors"]] == [
        (
            "review warning requires resolution: no_actionable_decisions: all "
            "rows are skip; no expert labels will be written"
        )
    ]
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_reports_review_progress_for_partial_template(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [_base_row(action="accept", finding_id="finding-accept"), _base_row(action="skip")],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        feedback_service=service,
    )

    assert summary["status"] == "pass"
    assert summary["counts"] == {"accept": 1, "skip": 1}
    assert summary["review_progress"] == {
        "actionable_count": 1,
        "skipped_count": 1,
        "needs_review_count": 1,
        "ready_to_write": True,
        "next_steps": [
            "leave unchecked rows as skip or review them later",
            "rerun dry-run with --fail-on-warnings before import",
        ],
    }
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_requires_human_reviewer(tmp_path):
    module = _load_import_module()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(input_path, [_base_row(action="accept")])

    with pytest.raises(ValueError, match="human expert"):
        module.import_review_decisions(
            input_path=input_path,
            reviewer="ai-reviewer-codex",
            feedback_service=FakeFeedbackService(),
        )


def test_import_review_decisions_rejects_invalid_rows(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(action="reject", issue_type="none"),
            _base_row(
                action="correct",
                evidence=[],
                suggested_target={"statement": "Preheating increased ductility by 14%."},
            ),
        ],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        feedback_service=service,
    )

    assert summary["status"] == "fail"
    assert summary["written_count"] == 0
    assert summary["warnings"] == []
    assert summary["affected_goals"] == []
    assert [error["message"] for error in summary["errors"]] == [
        "reject requires a valid issue_type",
        "correct requires at least one evidence_ref_id",
    ]
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_rejects_accept_with_protocol_gaps(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(
                action="accept",
                finding_id="finding-accept",
                protocol_readiness={
                    "status": "needs_correction",
                    "blocking_missing": ["variables", "direction_or_scope"],
                },
            ),
            _base_row(
                action="correct",
                finding_id="finding-correct",
                protocol_readiness={
                    "status": "needs_correction",
                    "blocking_missing": ["variables"],
                },
                suggested_target={
                    "statement": "Preheating increased ductility by 14%.",
                    "variables": ["preheating"],
                    "outcomes": ["ductility"],
                    "direction": "increase",
                    "scope_summary": "LPBF 316L",
                    "evidence_ref_ids": ["ev-1"],
                },
            ),
        ],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        feedback_service=service,
    )

    assert summary["status"] == "fail"
    assert summary["written_count"] == 0
    assert [error["message"] for error in summary["errors"]] == [
        (
            "accept requires protocol_readiness without blocking gaps; use "
            "correct or reject for: variables, direction_or_scope"
        )
    ]
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_rejects_accept_when_acceptance_gate_denies_it(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(
                action="accept",
                finding_id="finding-accept",
                acceptance_gate={
                    "accept_allowed": False,
                    "requires_correction": True,
                    "blocking_missing": [],
                },
            )
        ],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        feedback_service=service,
    )

    assert summary["status"] == "fail"
    assert summary["written_count"] == 0
    assert [error["message"] for error in summary["errors"]] == [
        "accept is blocked by acceptance_gate; use correct or reject"
    ]
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_rejects_accept_when_acceptance_gate_has_blockers(
    tmp_path,
):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(
                action="accept",
                finding_id="finding-accept",
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
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        feedback_service=service,
    )

    assert summary["status"] == "fail"
    assert summary["written_count"] == 0
    assert [error["message"] for error in summary["errors"]] == [
        (
            "accept is blocked by acceptance_gate.accept_blockers; "
            "use correct or reject for: verify_table_rows, table_row_alignment_uncertain"
        )
    ]
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_validates_current_dataset_refs(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(action="accept", finding_id="missing-finding"),
            _base_row(
                action="correct",
                finding_id="finding-correct",
                suggested_target={
                    "statement": "Preheating increased ductility by 14%.",
                    "evidence_ref_ids": ["missing-ev"],
                },
            ),
        ],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        feedback_service=service,
    )

    assert summary["status"] == "fail"
    assert summary["written_count"] == 0
    assert summary["warnings"] == []
    assert summary["affected_goals"] == []
    assert [error["message"] for error in summary["errors"]] == [
        "finding_id does not exist in current goal dataset",
        (
            "correct references evidence_ref_id(s) not present on current "
            "finding: missing-ev"
        ),
    ]
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_rejects_mismatched_claim_id(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(
                action="accept",
                finding_id="finding-accept",
                claim_id="claim-other",
            )
        ],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        feedback_service=service,
    )

    assert summary["status"] == "fail"
    assert summary["written_count"] == 0
    assert summary["warnings"] == []
    assert summary["affected_goals"] == []
    assert [error["message"] for error in summary["errors"]] == [
        "claim_id does not match current goal dataset finding"
    ]
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_warns_on_risky_accepts(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(
                action="accept",
                finding_id="finding-accept",
                recommended_action_code="accept_as_paper_level",
                review_reasons=[
                    "needs_cross_paper_confirmation",
                    "single_paper_evidence",
                ],
            ),
            _base_row(
                action="correct",
                finding_id="finding-correct",
                recommended_action_code="review_table_rows",
                review_reasons=["table_row_needs_expert_review"],
                suggested_target={
                    "statement": "Preheating increased ductility by 14%.",
                    "evidence_ref_ids": ["ev-1"],
                },
            ),
            _base_row(
                action="accept",
                finding_id="finding-accept",
                recommended_action_code="verify_table_rows",
            ),
            _base_row(
                action="correct",
                finding_id="finding-correct",
                recommended_action_code="review_table_variables",
                suggested_target={
                    "statement": "Preheating increased ductility by 14%.",
                    "evidence_ref_ids": ["ev-1"],
                },
            ),
        ],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        feedback_service=service,
    )

    assert summary["status"] == "pass"
    assert summary["written_count"] == 0
    assert summary["warnings"] == [
        {
            "line": 1,
            "action": "accept",
            "finding_id": "finding-accept",
            "message": (
                "recommended_action_code=accept_as_paper_level; "
                "review_reasons=needs_cross_paper_confirmation; "
                "expert_note required"
            ),
        },
        {
            "line": 2,
            "action": "correct",
            "finding_id": "finding-correct",
            "message": (
                "recommended_action_code=review_table_rows; "
                "review_reasons=table_row_needs_expert_review; "
                "expert_note required"
            ),
        },
        {
            "line": 3,
            "action": "accept",
            "finding_id": "finding-accept",
            "message": "recommended_action_code=verify_table_rows; expert_note required",
        },
        {
            "line": 4,
            "action": "correct",
            "finding_id": "finding-correct",
            "message": (
                "recommended_action_code=review_table_variables; expert_note required"
            ),
        },
    ]
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_can_fail_on_warnings(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(
                action="accept",
                finding_id="finding-accept",
                recommended_action_code="accept_as_paper_level",
                review_reasons=["needs_cross_paper_confirmation"],
            )
        ],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        fail_on_warnings=True,
        feedback_service=service,
    )

    assert summary["status"] == "fail"
    assert summary["written_count"] == 0
    assert summary["warnings"] == [
        {
            "line": 1,
            "action": "accept",
            "finding_id": "finding-accept",
            "message": (
                "recommended_action_code=accept_as_paper_level; "
                "review_reasons=needs_cross_paper_confirmation; "
                "expert_note required"
            ),
        }
    ]
    assert [error["message"] for error in summary["errors"]] == [
        (
            "review warning requires resolution: "
            "recommended_action_code=accept_as_paper_level; "
            "review_reasons=needs_cross_paper_confirmation; "
            "expert_note required"
        )
    ]
    assert service.feedback == []
    assert service.curations == []


def test_import_review_decisions_accepts_risky_rows_with_expert_note(tmp_path):
    module = _load_import_module()
    service = FakeFeedbackService()
    input_path = tmp_path / "review.jsonl"
    _write_jsonl(
        input_path,
        [
            _base_row(
                action="accept",
                finding_id="finding-accept",
                recommended_action_code="accept_as_paper_level",
                review_reasons=["needs_cross_paper_confirmation"],
                expert_note=(
                    "Confirmed as paper-level only; not a cross-paper conclusion."
                ),
            )
        ],
    )

    summary = module.import_review_decisions(
        input_path=input_path,
        reviewer="materials-expert@example.com",
        dry_run=True,
        fail_on_warnings=True,
        feedback_service=service,
    )

    assert summary["status"] == "pass"
    assert summary["warnings"] == []
    assert summary["errors"] == []
    assert summary["counts"] == {"accept": 1}
    assert service.feedback == []
