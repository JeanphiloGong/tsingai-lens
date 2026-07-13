from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_goal_expert_loop_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "check_goal_expert_loop.py"
    )
    spec = importlib.util.spec_from_file_location("check_goal_expert_loop", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _findings_payload(status: str = "pass"):
    return {
        "status": status,
        "goals": [
            {
                "goal_id": "goal-1",
                "primary_finding_count": 1,
                "direct_evidence_count": 2,
            },
            {
                "goal_id": "goal-2",
                "primary_finding_count": 1,
                "direct_evidence_count": 1,
            },
        ],
    }


def _dataset_payload(status: str = "pass"):
    return {
        "status": status,
        "goals": [
            {
                "goal_id": "goal-1",
                "item_count": 1,
                "training_ready_count": 1,
                "training_message_ready_count": 1,
                "review_candidate_count": 0,
            },
            {
                "goal_id": "goal-2",
                "item_count": 2,
                "training_ready_count": 0,
                "training_message_ready_count": 0,
                "review_candidate_count": 2,
            },
        ],
    }


def test_check_goal_expert_loop_passes_when_reviewable_and_protocol_ready(monkeypatch):
    check = _load_goal_expert_loop_module()

    monkeypatch.setattr(
        check,
        "_load_sibling_module",
        lambda _filename, module_name: (
            type(
                "FindingsModule",
                (),
                {"check_goal_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_goal_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: _dataset_payload())},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        goal_ids=("goal-1", "goal-2"),
    )

    assert summary["status"] == "pass"
    assert summary["layers"]["expert_review"]["status"] == "pass"
    assert summary["layers"]["dataset_accumulation"]["training_ready_goal_count"] == 1
    assert summary["layers"]["experiment_design"]["eligible_goal_ids"] == ["goal-1"]


def test_check_goal_expert_loop_strict_mode_requires_all_training_ready(monkeypatch):
    check = _load_goal_expert_loop_module()

    monkeypatch.setattr(
        check,
        "_load_sibling_module",
        lambda _filename, module_name: (
            type(
                "FindingsModule",
                (),
                {"check_goal_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_goal_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: _dataset_payload())},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        goal_ids=("goal-1", "goal-2"),
        require_all_training_ready=True,
    )

    assert summary["status"] == "fail"
    assert summary["layers"]["dataset_accumulation"]["status"] == "fail"
    assert summary["layers"]["experiment_design"]["status"] == "pass"


def test_check_goal_expert_loop_fails_without_protocol_ready_goal(monkeypatch):
    check = _load_goal_expert_loop_module()
    dataset = _dataset_payload()
    for goal in dataset["goals"]:
        goal["training_ready_count"] = 0
        goal["training_message_ready_count"] = 0

    monkeypatch.setattr(
        check,
        "_load_sibling_module",
        lambda _filename, module_name: (
            type(
                "FindingsModule",
                (),
                {"check_goal_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_goal_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: dataset)},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        goal_ids=("goal-1", "goal-2"),
    )

    assert summary["status"] == "fail"
    assert summary["layers"]["dataset_accumulation"]["status"] == "fail"
    assert summary["layers"]["experiment_design"]["status"] == "fail"
