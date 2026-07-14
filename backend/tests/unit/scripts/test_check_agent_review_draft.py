from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_check_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "check_agent_review_draft.py"
    )
    spec = importlib.util.spec_from_file_location(
        "check_agent_review_draft",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _row(**overrides):
    row = {
        "collection_id": "col-1",
        "goal_id": "goal-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
        "action": "skip",
        "statement": "Preheating increased ductility by 14%.",
        "acceptance_gate": {
            "status": "review_required",
            "accept_allowed": True,
            "requires_correction": False,
            "blocking_missing": [],
            "review_checks": ["Confirm the finding is paper-level only."],
        },
        "evidence": [
            {
                "evidence_ref_id": "ev-1",
                "quote": "Preheating increased ductility by 14%.",
            }
        ],
        "agent_review": {
            "reviewer": "ai-reviewer-codex",
            "recommendation": "accept",
            "note": "The quote directly supports the paper-level finding.",
        },
    }
    row.update(overrides)
    return row


def test_check_agent_review_draft_accepts_safe_silver_draft(tmp_path):
    module = _load_check_module()
    input_path = tmp_path / "agent-draft.jsonl"
    _write_jsonl(
        input_path,
        [
            _row(),
            _row(
                finding_id="finding-2",
                agent_review={
                    "reviewer": "agent-materials-review",
                    "recommendation": "correct",
                    "note": "Outcome should be ductility.",
                    "suggested_target": {
                        "statement": "Preheating increased ductility by 14%.",
                        "evidence_ref_ids": ["ev-1"],
                    },
                },
            ),
        ],
    )

    summary = module.check_agent_review_draft(input_path)

    assert summary["status"] == "pass"
    assert summary["total_rows"] == 2
    assert summary["agent_reviewed_count"] == 2
    assert summary["counts"] == {"accept": 1, "correct": 1}
    assert summary["goals"] == [
        {
            "collection_id": "col-1",
            "goal_id": "goal-1",
            "total_rows": 2,
            "agent_reviewed_count": 2,
            "accept_count": 1,
            "reject_count": 0,
            "correct_count": 1,
            "unclear_count": 0,
            "skip_count": 0,
            "missing_count": 0,
            "first_unresolved_finding_id": "",
            "actionable_count": 2,
            "unresolved_count": 0,
            "next_action": "human confirm actionable recommendations",
        }
    ]
    assert summary["errors"] == []
    assert summary["warnings"] == [
        {
            "line": 1,
            "finding_id": "finding-1",
            "message": (
                "human must verify acceptance checks: Confirm the finding is "
                "paper-level only."
            ),
        }
    ]
    assert summary["human_handoff"]["ready_for_human_review"] is True
    assert "Rows remain action=skip" in summary["human_handoff"]["import_guard"]
    text = module.render_text_summary(summary)
    assert "Goal handoff:" in text
    assert (
        "- goal-1: reviewed=2 accept=1 reject=0 correct=1 unclear=0 "
        "next=human confirm actionable recommendations"
    ) in text


def test_check_agent_review_draft_rejects_import_actions(tmp_path):
    module = _load_check_module()
    input_path = tmp_path / "agent-draft.jsonl"
    _write_jsonl(input_path, [_row(action="accept")])

    summary = module.check_agent_review_draft(input_path)

    assert summary["status"] == "fail"
    assert summary["errors"] == [
        {
            "line": 1,
            "finding_id": "finding-1",
            "message": (
                "agent drafts must keep action=skip; human review sets import actions"
            ),
        }
    ]


def test_check_agent_review_draft_blocks_accept_when_gate_blocks(tmp_path):
    module = _load_check_module()
    input_path = tmp_path / "agent-draft.jsonl"
    _write_jsonl(
        input_path,
        [
            _row(
                acceptance_gate={
                    "status": "correction_required",
                    "accept_allowed": False,
                    "requires_correction": True,
                    "blocking_missing": ["variables"],
                    "review_checks": [],
                }
            )
        ],
    )

    summary = module.check_agent_review_draft(input_path)

    assert summary["status"] == "fail"
    assert [error["message"] for error in summary["errors"]] == [
        "agent accept recommendation is blocked by acceptance_gate",
        "agent accept recommendation has blocking gaps: variables",
    ]


def test_check_agent_review_draft_warnings_can_fail(tmp_path):
    module = _load_check_module()
    input_path = tmp_path / "agent-draft.jsonl"
    _write_jsonl(
        input_path,
        [
            _row(
                agent_review={
                    "reviewer": "ai-reviewer-codex",
                    "recommendation": "unclear",
                }
            )
        ],
    )

    summary = module.check_agent_review_draft(input_path, fail_on_warnings=True)

    assert summary["status"] == "fail"
    assert summary["errors"] == []
    assert summary["warnings"] == [
        {
            "line": 1,
            "finding_id": "finding-1",
            "message": "agent reviewed row should include agent_review.note",
        }
    ]


def test_check_agent_review_draft_groups_unresolved_rows_by_goal(tmp_path):
    module = _load_check_module()
    input_path = tmp_path / "agent-draft.jsonl"
    _write_jsonl(
        input_path,
        [
            _row(
                finding_id="finding-1",
                agent_review={
                    "reviewer": "ai-reviewer-codex",
                    "recommendation": "unclear",
                    "note": "Evidence needs expert judgment.",
                },
            ),
            _row(finding_id="finding-2", agent_review={}),
        ],
    )

    summary = module.check_agent_review_draft(input_path)

    assert summary["goals"] == [
        {
            "collection_id": "col-1",
            "goal_id": "goal-1",
            "total_rows": 2,
            "agent_reviewed_count": 1,
            "accept_count": 0,
            "reject_count": 0,
            "correct_count": 0,
            "unclear_count": 1,
            "skip_count": 0,
            "missing_count": 1,
            "first_unresolved_finding_id": "finding-1",
            "actionable_count": 0,
            "unresolved_count": 2,
            "next_action": "resolve unclear or missing agent recommendations",
        }
    ]
