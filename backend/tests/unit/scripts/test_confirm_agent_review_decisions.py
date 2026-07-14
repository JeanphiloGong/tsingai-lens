from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_confirm_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "confirm_agent_review_decisions.py"
    )
    spec = importlib.util.spec_from_file_location(
        "confirm_agent_review_decisions",
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
        "claim_id": "claim-1",
        "action": "skip",
        "issue_type": "",
        "expert_note": "",
        "statement": "Preheating increased ductility by 14%.",
        "acceptance_gate": {
            "accept_allowed": True,
            "blocking_missing": [],
        },
        "protocol_blocking_missing": [],
        "agent_review": {
            "reviewer": "agent-materials-review",
            "recommendation": "accept",
            "note": "Evidence supports the paper-level statement.",
            "human_confirmed": True,
        },
    }
    row.update(overrides)
    return row


def test_confirm_agent_review_decisions_keeps_unconfirmed_rows_skipped():
    module = _load_confirm_module()

    rows = module.confirm_agent_review_decisions(
        [_row(action="accept", agent_review={"recommendation": "accept"})]
    )

    assert rows[0]["action"] == "skip"


def test_confirm_agent_review_decisions_accepts_confirmed_accept():
    module = _load_confirm_module()

    rows = module.confirm_agent_review_decisions([_row()])

    assert rows[0]["action"] == "accept"
    assert rows[0]["expert_note"] == "Evidence supports the paper-level statement."


def test_confirm_agent_review_decisions_converts_confirmed_reject():
    module = _load_confirm_module()

    rows = module.confirm_agent_review_decisions(
        [
            _row(
                agent_review={
                    "reviewer": "agent-materials-review",
                    "recommendation": "reject",
                    "issue_type": "wrong_direction",
                    "note": "The direction is reversed.",
                    "human_confirmed": True,
                }
            )
        ]
    )

    assert rows[0]["action"] == "reject"
    assert rows[0]["issue_type"] == "wrong_direction"
    assert rows[0]["expert_note"] == "The direction is reversed."


def test_confirm_agent_review_decisions_converts_confirmed_correction():
    module = _load_confirm_module()
    target = {
        "statement": "Preheating increased ductility by 14%.",
        "variables": ["preheating"],
        "outcomes": ["ductility"],
        "direction": "increase",
        "evidence_ref_ids": ["ev-1"],
    }

    rows = module.confirm_agent_review_decisions(
        [
            _row(
                agent_review={
                    "reviewer": "agent-materials-review",
                    "recommendation": "correct",
                    "note": "Use the narrower ductility finding.",
                    "suggested_target": target,
                    "human_confirmed": True,
                }
            )
        ]
    )

    assert rows[0]["action"] == "correct"
    assert rows[0]["suggested_target"] == target
    assert rows[0]["curated_evidence_ref_ids"] == ["ev-1"]


def test_confirm_agent_review_decisions_rejects_blocked_accept():
    module = _load_confirm_module()

    try:
        module.confirm_agent_review_decisions(
            [
                _row(
                    acceptance_gate={
                        "accept_allowed": False,
                        "blocking_missing": ["variables"],
                    }
                )
            ]
        )
    except ValueError as exc:
        assert str(exc) == "line 1: confirmed accept is blocked by acceptance_gate"
    else:
        raise AssertionError("expected blocked accept to fail")


def test_confirm_agent_review_decisions_reads_jsonl(tmp_path):
    module = _load_confirm_module()
    input_path = tmp_path / "agent-reviewed-findings.jsonl"
    input_path.write_text(json.dumps(_row()) + "\n", encoding="utf-8")

    rows = module.confirm_agent_review_decisions(module.read_jsonl(input_path))

    assert rows[0]["finding_id"] == "finding-1"
    assert rows[0]["action"] == "accept"
