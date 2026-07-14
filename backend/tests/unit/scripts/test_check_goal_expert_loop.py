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
                "question": "How does preheating affect ductility?",
                "primary_finding_count": 1,
                "direct_evidence_count": 2,
            },
            {
                "goal_id": "goal-2",
                "question": "How does porosity affect corrosion?",
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
                "protocol_ready_count": 1,
                "review_candidate_count": 0,
                "by_error_category": {"none": 1},
                "by_review_reason": {},
                "by_system_warning": {},
                "by_review_candidate_reason": {},
                "by_review_candidate_warning": {},
            },
            {
                "goal_id": "goal-2",
                "item_count": 2,
                "training_ready_count": 0,
                "training_message_ready_count": 0,
                "protocol_ready_count": 0,
                "review_candidate_count": 2,
                "next_review_finding_id": "finding-review-1",
                "next_review_action": {
                    "code": "verify_table_rows",
                    "label": "verify parsed table rows before accepting or correcting",
                },
                "by_error_category": {"variable_error": 1, "direction_error": 1},
                "by_review_reason": {
                    "single_paper_evidence": 2,
                    "needs_cross_paper_confirmation": 1,
                },
                "by_system_warning": {"table_row_alignment_uncertain": 1},
                "by_review_candidate_reason": {
                    "single_paper_evidence": 2,
                    "needs_cross_paper_confirmation": 1,
                },
                "by_review_candidate_warning": {"table_row_alignment_uncertain": 1},
            },
        ],
    }


def _completed_dataset_payload(status: str = "pass"):
    payload = _dataset_payload(status)
    for goal in payload["goals"]:
        goal["training_ready_count"] = max(1, goal["training_ready_count"])
        goal["training_message_ready_count"] = max(1, goal["training_message_ready_count"])
        goal["protocol_ready_count"] = max(1, goal["protocol_ready_count"])
        goal["review_candidate_count"] = 0
    return payload


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
    assert summary["completion_status"] == "incomplete"
    assert summary["layers"]["expert_review"]["status"] == "pass"
    assert summary["layers"]["dataset_accumulation"]["training_ready_goal_count"] == 1
    assert summary["layers"]["dataset_accumulation"]["protocol_ready_goal_count"] == 1
    assert summary["layers"]["experiment_design"]["eligible_goal_ids"] == ["goal-1"]
    assert summary["layers"]["experiment_design"]["runtime_contract"]["status"] == (
        "not_checked"
    )
    assert summary["remaining_work"] == {
        "review_candidate_count": 2,
        "goals_without_training_ready": ["goal-2"],
        "goals_without_training_messages": ["goal-2"],
        "goals_without_protocol_ready": ["goal-2"],
        "pending_goals": [
            {
                "goal_id": "goal-2",
                "question": "How does porosity affect corrosion?",
                "review_candidate_count": 2,
                "training_ready_count": 0,
                "training_message_ready_count": 0,
                "protocol_ready_count": 0,
                "next_action": "review_candidates",
                "next_review_action": {
                    "code": "verify_table_rows",
                    "label": "verify parsed table rows before accepting or correcting",
                },
                "href": "/collections/col-1/goals/goal-2?review=queue&finding_id=finding-review-1",
                "next_review_finding_id": "finding-review-1",
            }
        ],
        "by_error_category": {"direction_error": 1, "variable_error": 1},
        "by_review_reason": {
            "single_paper_evidence": 2,
            "needs_cross_paper_confirmation": 1,
        },
        "by_system_warning": {"table_row_alignment_uncertain": 1},
    }


def test_check_goal_expert_loop_require_complete_fails_on_remaining_work(monkeypatch):
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
        require_complete=True,
    )

    assert summary["status"] == "fail"
    assert summary["completion_status"] == "incomplete"
    assert summary["require_complete"] is True


def test_check_goal_expert_loop_renders_human_review_summary(monkeypatch):
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
        require_complete=True,
    )
    text = check.render_text_summary(summary)

    assert "Lens expert loop: fail (incomplete)" in text
    assert "review candidates: 2" in text
    assert "How does porosity affect corrosion?" in text
    assert (
        "open: /collections/col-1/goals/goal-2?review=queue&finding_id=finding-review-1"
        in text
    )
    assert (
        "review action: verify parsed table rows before accepting or correcting"
        in text
    )
    assert "direction_error: 1" in text
    assert "variable_error: 1" in text
    assert "single_paper_evidence: 2" in text
    assert "needs_cross_paper_confirmation: 1" in text
    assert "table_row_alignment_uncertain: 1" in text
    assert "Next commands:" in text
    assert (
        "python3 scripts/evaluation/expert_gold/check_goal_dataset_quality.py --collection-id col-1 --format review-packet"
        in text
    )
    assert (
        "python3 scripts/evaluation/expert_gold/check_goal_dataset_quality.py --collection-id col-1 --format review-jsonl"
        in text
    )
    assert (
        "python3 scripts/evaluation/expert_gold/import_goal_review_decisions.py "
        "reviewed-findings.jsonl --reviewer <human-reviewer> --dry-run --fail-on-warnings"
        in text
    )
    assert (
        "python3 scripts/evaluation/expert_gold/check_goal_dataset_quality.py --collection-id col-1 --format messages-jsonl"
        in text
    )


def test_check_goal_expert_loop_points_message_gaps_to_training_samples(monkeypatch):
    check = _load_goal_expert_loop_module()
    dataset = _completed_dataset_payload()
    dataset["goals"][1]["training_message_ready_count"] = 0
    dataset["goals"][1]["protocol_ready_count"] = 0

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
        require_complete=True,
    )

    assert summary["remaining_work"]["pending_goals"] == [
        {
            "goal_id": "goal-2",
            "question": "How does porosity affect corrosion?",
            "review_candidate_count": 0,
            "training_ready_count": 1,
            "training_message_ready_count": 0,
            "protocol_ready_count": 0,
            "next_action": "inspect_training_messages",
            "next_review_action": {},
            "href": "/collections/col-1/goals/goal-2?review=training_ready",
            "next_review_finding_id": "",
        }
    ]


def test_check_goal_expert_loop_require_complete_passes_when_no_work_remains(monkeypatch):
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
                {"check_goal_dataset_quality": staticmethod(lambda **_: _completed_dataset_payload())},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        goal_ids=("goal-1", "goal-2"),
        require_complete=True,
    )

    assert summary["status"] == "pass"
    assert summary["completion_status"] == "complete"
    assert summary["remaining_work"]["review_candidate_count"] == 0
    assert "Next commands:" not in check.render_text_summary(summary)


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
    assert summary["completion_status"] == "incomplete"
    assert summary["layers"]["dataset_accumulation"]["status"] == "fail"
    assert summary["layers"]["experiment_design"]["status"] == "pass"


def test_check_goal_expert_loop_points_protocol_gaps_to_training_samples(monkeypatch):
    check = _load_goal_expert_loop_module()
    dataset = _completed_dataset_payload()
    dataset["goals"][1]["protocol_ready_count"] = 0

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
        require_complete=True,
    )

    assert summary["status"] == "fail"
    assert summary["layers"]["experiment_design"]["status"] == "pass"
    assert summary["completion_status"] == "incomplete"
    assert summary["remaining_work"]["pending_goals"] == [
        {
            "goal_id": "goal-2",
            "question": "How does porosity affect corrosion?",
            "review_candidate_count": 0,
            "training_ready_count": 1,
            "training_message_ready_count": 1,
            "protocol_ready_count": 0,
            "next_action": "inspect_protocol_inputs",
            "next_review_action": {},
            "href": "/collections/col-1/goals/goal-2?review=training_ready",
            "next_review_finding_id": "",
        }
    ]


def test_check_goal_expert_loop_fails_without_protocol_ready_goal(monkeypatch):
    check = _load_goal_expert_loop_module()
    dataset = _dataset_payload()
    for goal in dataset["goals"]:
        goal["training_ready_count"] = 0
        goal["training_message_ready_count"] = 0
        goal["protocol_ready_count"] = 0

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


def test_check_goal_expert_loop_fails_when_runtime_plan_routes_are_missing(monkeypatch):
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
                {
                    "check_goal_dataset_quality": staticmethod(
                        lambda **_: _completed_dataset_payload()
                    )
                },
            )
        ),
    )
    monkeypatch.setattr(
        check,
        "_fetch_openapi_paths",
        lambda _base_url: {
            "/api/v1/collections/{collection_id}/goals/{goal_id}/analysis": {
                "get": {}
            }
        },
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        goal_ids=("goal-1", "goal-2"),
        api_base_url="http://localhost:5173",
        require_complete=True,
    )
    text = check.render_text_summary(summary)

    assert summary["status"] == "fail"
    assert summary["completion_status"] == "complete"
    assert summary["layers"]["experiment_design"]["status"] == "fail"
    assert summary["layers"]["experiment_design"]["runtime_contract"]["status"] == "fail"
    assert "runtime contract: fail" in text
    assert (
        "missing route: GET /api/v1/collections/{collection_id}/goals/{goal_id}/experiment-plans"
        in text
    )
    assert (
        "missing route: POST /api/v1/collections/{collection_id}/goals/{goal_id}/experiment-plans"
        in text
    )
    assert (
        "missing route: PATCH /api/v1/collections/{collection_id}/goals/{goal_id}/experiment-plans/{plan_id}"
        in text
    )


def test_check_goal_expert_loop_passes_when_runtime_plan_routes_exist(monkeypatch):
    check = _load_goal_expert_loop_module()
    plan_list_path = (
        "/api/v1/collections/{collection_id}/goals/{goal_id}/experiment-plans"
    )
    plan_detail_path = f"{plan_list_path}/{{plan_id}}"

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
                {
                    "check_goal_dataset_quality": staticmethod(
                        lambda **_: _completed_dataset_payload()
                    )
                },
            )
        ),
    )
    monkeypatch.setattr(
        check,
        "_fetch_openapi_paths",
        lambda _base_url: {
            plan_list_path: {"get": {}, "post": {}},
            plan_detail_path: {"patch": {}},
        },
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        goal_ids=("goal-1", "goal-2"),
        api_base_url="http://localhost:5173",
        require_complete=True,
    )

    assert summary["status"] == "pass"
    assert summary["completion_status"] == "complete"
    assert summary["layers"]["experiment_design"]["runtime_contract"]["status"] == "pass"
