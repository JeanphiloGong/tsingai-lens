from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_prepare_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "prepare_agent_review_draft.py"
    )
    spec = importlib.util.spec_from_file_location(
        "prepare_agent_review_draft",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(**overrides):
    row = {
        "collection_id": "col-1",
        "goal_id": "goal-1",
        "finding_id": "finding-1",
        "action": "skip",
        "statement": "Preheating increased ductility by 14%.",
        "variables": ["preheating"],
        "outcomes": ["ductility"],
        "direction": "increase",
        "recommended_action_code": "accept_as_paper_level",
        "acceptance_gate": {
            "accept_allowed": True,
            "blocking_missing": [],
            "review_checks": ["Confirm this is paper-level only."],
        },
        "curated_evidence_ref_ids": ["ev-1"],
        "suggested_target": {
            "statement": "Preheating increased ductility by 14%.",
            "evidence_ref_ids": ["ev-1"],
        },
    }
    row.update(overrides)
    return row


def test_prepare_agent_review_draft_keeps_actions_skipped():
    module = _load_prepare_module()

    rows = module.prepare_agent_review_draft(
        [_row(action="accept")],
        reviewer="agent-materials-review",
    )

    assert rows[0]["action"] == "skip"
    assert rows[0]["agent_review"] == {
        "reviewer": "agent-materials-review",
        "recommendation": "unclear",
        "issue_type": "",
        "note": "Verify before recommending: Confirm this is paper-level only.",
        "suggested_target": {
            "statement": "Preheating increased ductility by 14%.",
            "evidence_ref_ids": ["ev-1"],
        },
    }


def test_prepare_agent_review_draft_preserves_blocked_row_note():
    module = _load_prepare_module()

    rows = module.prepare_agent_review_draft(
        [
            _row(
                acceptance_gate={
                    "accept_allowed": False,
                    "blocking_missing": ["variables"],
                    "review_checks": [],
                },
                protocol_blocking_missing=["variables"],
            )
        ]
    )

    assert rows[0]["agent_review"]["recommendation"] == "unclear"
    assert rows[0]["agent_review"]["note"] == "Protocol draft is missing: variables"


def test_prepare_agent_review_draft_rejects_human_reviewer_ids():
    module = _load_prepare_module()

    try:
        module.prepare_agent_review_draft([_row()], reviewer="human@example.com")
    except ValueError as exc:
        assert str(exc) == "reviewer must start with ai-reviewer or agent-"
    else:
        raise AssertionError("expected invalid reviewer to fail")


def test_prepare_agent_review_draft_reads_jsonl(tmp_path):
    module = _load_prepare_module()
    input_path = tmp_path / "reviewed-findings.jsonl"
    input_path.write_text(json.dumps(_row()) + "\n", encoding="utf-8")

    rows = module.prepare_agent_review_draft(module.read_jsonl(input_path))

    assert rows[0]["finding_id"] == "finding-1"
    assert rows[0]["agent_review"]["reviewer"] == "ai-reviewer-codex"
