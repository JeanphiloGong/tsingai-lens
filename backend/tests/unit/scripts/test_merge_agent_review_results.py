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
        "analysis_version": 2,
        "finding_id": "finding-1",
        "action": "accept",
        "statement": "Preheating increased ductility.",
    }
    row.update(overrides)
    return row


def _agent_row(**overrides):
    row = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 2,
        "finding_id": "finding-1",
        "agent_review": {
            "reviewer": "ai-reviewer-codex",
            "recommendation": "correct",
            "issue_type": "wrong_outcome",
            "note": "Evidence supports a narrower ductility finding.",
            "human_confirmed": True,
            "curated_finding": _finding(),
        },
    }
    row.update(overrides)
    return row


def _finding(**overrides):
    finding = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 2,
        "finding_id": "finding-1",
        "statement": "Preheating increased ductility by 14%.",
        "factors": ["preheating"],
        "outcome": "ductility",
        "direction": "increase",
        "assertion_strength": "associative",
        "attribution_scope": "isolated_effect",
        "synthesis_status": "insufficient_confirmation",
        "certainty": 0.5,
        "display_rank": 0,
        "mechanisms": [],
        "scientific_context": {"material": [], "sample": [], "process": [], "test": []},
        "limitations": ["One directly contributing paper."],
        "paper_contributions": [
            {
                "document_id": "paper-1",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["ev-1"],
                "contradicting_evidence_ids": [],
                "context_evidence_ids": [],
                "condition_boundary_evidence_ids": [],
            }
        ],
        "origin": "system_generated",
        "source_analysis_version": None,
        "parent_finding_id": None,
        "created_by_user_id": None,
        "created_by_tool_call_id": None,
        "created_at": None,
    }
    finding.update(overrides)
    return finding


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
            "analysis_version": 2,
            "finding_id": "finding-1",
            "action": "skip",
            "statement": "Preheating increased ductility.",
            "agent_review": {
                "reviewer": "ai-reviewer-codex",
                "recommendation": "correct",
                "issue_type": "wrong_outcome",
                "note": "Evidence supports a narrower ductility finding.",
                "human_confirmed": False,
                "curated_finding": _finding(),
            },
        }
    ]


def test_merge_agent_review_results_accepts_flat_agent_rows():
    module = _load_merge_module()

    rows = module.merge_agent_review_results(
        decision_rows=[_decision_row()],
        agent_rows=[
            {
                "collection_id": "col-1",
                "objective_id": "objective-1",
                "analysis_version": 2,
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
        assert str(exc) == "line 2: duplicate Finding identity"
    else:
        raise AssertionError("expected duplicate finding to fail")


def test_merge_agent_review_results_reads_jsonl(tmp_path):
    module = _load_merge_module()
    path = tmp_path / "agent-results.jsonl"
    path.write_text(json.dumps(_agent_row()) + "\n", encoding="utf-8")

    rows = module.read_jsonl(path)

    assert rows[0]["finding_id"] == "finding-1"


def test_merge_agent_review_results_does_not_cross_analysis_versions():
    module = _load_merge_module()

    rows = module.merge_agent_review_results(
        decision_rows=[_decision_row(analysis_version=1), _decision_row(analysis_version=2)],
        agent_rows=[
            _agent_row(
                analysis_version=2,
                agent_review={
                    "reviewer": "agent-materials-review",
                    "recommendation": "accept",
                    "note": "Version 2 is supported.",
                },
            )
        ],
    )

    assert "agent_review" not in rows[0]
    assert rows[1]["agent_review"]["recommendation"] == "accept"
