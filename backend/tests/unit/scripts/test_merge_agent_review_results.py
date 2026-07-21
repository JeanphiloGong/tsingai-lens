from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_merge_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "merge_agent_review_results.py"
    )
    spec = importlib.util.spec_from_file_location("merge_agent_review_results", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _decision_row(**overrides):
    row = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
        "action": "accept",
        "statement": "Preheating increased ductility.",
    }
    row.update(overrides)
    return row


def _agent_row(**overrides):
    row = {
        "finding_id": "finding-1",
        "agent_review": {
            "reviewer": "ai-reviewer-codex",
            "recommendation": "correct",
            "issue_type": "wrong_outcome",
            "note": "Evidence supports a narrower ductility finding.",
            "human_confirmed": True,
            "suggested_target": {
                "statement": "Preheating increased ductility by 14%.",
                "evidence_ref_ids": ["ev-1"],
            },
        },
    }
    row.update(overrides)
    return row


def test_merge_agent_review_results_keeps_import_actions_skipped():
    module = _load_merge_module()

    rows = module.merge_agent_review_results(
        decision_rows=[_decision_row()],
        agent_rows=[_agent_row()],
    )

    assert rows == [
        {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "finding_id": "finding-1",
            "claim_id": "claim-1",
            "action": "skip",
            "statement": "Preheating increased ductility.",
            "agent_review": {
                "reviewer": "ai-reviewer-codex",
                "recommendation": "correct",
                "issue_type": "wrong_outcome",
                "note": "Evidence supports a narrower ductility finding.",
                "human_confirmed": False,
                "suggested_target": {
                    "statement": "Preheating increased ductility by 14%.",
                    "evidence_ref_ids": ["ev-1"],
                },
            },
        }
    ]


def test_merge_agent_review_results_accepts_flat_agent_rows():
    module = _load_merge_module()

    rows = module.merge_agent_review_results(
        decision_rows=[_decision_row()],
        agent_rows=[
            {
                "finding_id": "finding-1",
                "reviewer": "agent-materials-review",
                "recommendation": "accept",
                "note": "The quote directly supports the paper-level finding.",
            }
        ],
    )

    assert rows[0]["action"] == "skip"
    assert rows[0]["agent_review"] == {
        "reviewer": "agent-materials-review",
        "recommendation": "accept",
        "note": "The quote directly supports the paper-level finding.",
        "human_confirmed": False,
    }


def test_merge_agent_review_results_rejects_human_reviewer():
    module = _load_merge_module()

    try:
        module.merge_agent_review_results(
            decision_rows=[_decision_row()],
            agent_rows=[
                _agent_row(
                    agent_review={
                        "reviewer": "human@example.com",
                        "recommendation": "accept",
                    }
                )
            ],
        )
    except ValueError as exc:
        assert "must start with ai-reviewer or agent-" in str(exc)
    else:
        raise AssertionError("expected invalid reviewer to fail")


def test_merge_agent_review_results_rejects_duplicate_findings():
    module = _load_merge_module()

    try:
        module.merge_agent_review_results(
            decision_rows=[_decision_row()],
            agent_rows=[_agent_row(), _agent_row()],
        )
    except ValueError as exc:
        assert str(exc) == "line 2: duplicate finding_id finding-1"
    else:
        raise AssertionError("expected duplicate finding to fail")


def test_merge_agent_review_results_reads_jsonl(tmp_path):
    module = _load_merge_module()
    path = tmp_path / "agent-results.jsonl"
    path.write_text(json.dumps(_agent_row()) + "\n", encoding="utf-8")

    rows = module.read_jsonl(path)

    assert rows[0]["finding_id"] == "finding-1"
