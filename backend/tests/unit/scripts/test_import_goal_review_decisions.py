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
                    "dataset_use_status": "training_ready",
                    "training_evidence_refs": [{"evidence_ref_id": "ev-1"}],
                },
                {
                    "finding_id": "finding-correct",
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
                    "dataset_use_status": "review_candidate",
                    "training_evidence_refs": [{"evidence_ref_id": "ev-1"}],
                },
                {"finding_id": "finding-reject", "dataset_use_status": "rejected"},
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
            }
        ],
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
    assert summary["affected_goals"] == []
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
                "review_reasons=needs_cross_paper_confirmation"
            ),
        },
        {
            "line": 2,
            "action": "correct",
            "finding_id": "finding-correct",
            "message": (
                "recommended_action_code=review_table_rows; "
                "review_reasons=table_row_needs_expert_review"
            ),
        },
    ]
    assert service.feedback == []
    assert service.curations == []
