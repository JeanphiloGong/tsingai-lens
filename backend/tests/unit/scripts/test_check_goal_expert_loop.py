from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.error import HTTPError


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
        "objectives": [
            {
                "objective_id": "objective-1",
                "question": "How does preheating affect ductility?",
                "primary_finding_count": 1,
                "direct_evidence_count": 2,
            },
            {
                "objective_id": "objective-2",
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
                "objective_id": "objective-1",
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
                "objective_id": "objective-2",
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


def _runtime_paths(check):
    plan_list_path = check.PLAN_LIST_PATH
    plan_detail_path = check.PLAN_DETAIL_PATH
    return {
        check.GOAL_SESSION_PATH: {"post": {}},
        check.GOAL_SESSION_MESSAGE_PATH: {"post": {}},
        plan_list_path: {"get": {}, "post": {}},
        plan_detail_path: {"patch": {}},
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
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: _dataset_payload())},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
    )

    assert summary["status"] == "pass"
    assert summary["completion_status"] == "incomplete"
    assert summary["layers"]["expert_review"]["status"] == "pass"
    assert summary["layers"]["dataset_accumulation"]["training_ready_goal_count"] == 1
    assert summary["layers"]["dataset_accumulation"]["protocol_ready_goal_count"] == 1
    assert summary["layers"]["experiment_design"]["eligible_objective_ids"] == ["objective-1"]
    assert summary["layers"]["experiment_design"]["runtime_contract"]["status"] == (
        "not_checked"
    )
    assert summary["expert_satisfaction"] == {
        "status": "blocked",
        "criteria": [
            {
                "key": "expert_review",
                "title": "Expert review usable",
                "requirement": (
                    "Findings are clear, evidence is jumpable, and rows can be "
                    "accepted, rejected, or corrected."
                ),
                "satisfied": True,
                "status": "satisfied",
                "next_step": (
                    "Review candidates are available for human accept, reject, "
                    "or correct decisions."
                ),
            },
            {
                "key": "dataset_accumulation",
                "title": "Dataset accumulation usable",
                "requirement": (
                    "Human labels enter training_ready and exportable messages "
                    "for every checked goal."
                ),
                "satisfied": False,
                "status": "blocked",
                "next_step": (
                    "Import human-confirmed accept, reject, or correct decisions, "
                    "then rerun dataset export checks."
                ),
            },
            {
                "key": "experiment_design",
                "title": "Experiment design usable",
                "requirement": (
                    "Goal Copilot can consume curated Findings and save traceable "
                    "protocol drafts."
                ),
                "satisfied": False,
                "status": "blocked",
                "next_step": (
                    "Review or correct findings until every checked goal has "
                    "protocol-ready inputs."
                ),
            },
        ],
    }
    assert summary["remaining_work"] == {
        "review_candidate_count": 2,
        "goals_without_training_ready": ["objective-2"],
        "goals_without_training_messages": ["objective-2"],
        "goals_without_protocol_ready": ["objective-2"],
        "protocol_ready_goals": [
            {
                "objective_id": "objective-1",
                "question": "How does preheating affect ductility?",
                "training_ready_count": 1,
                "training_message_ready_count": 1,
                "protocol_ready_count": 1,
                "assistant_url": "/collections/col-1/assistant?objective_id=objective-1",
                "training_ready_url": "/collections/col-1/objectives/objective-1?review=training_ready",
            }
        ],
        "pending_goals": [
            {
                "objective_id": "objective-2",
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
                "href": "/collections/col-1/objectives/objective-2?review=queue&finding_id=finding-review-1",
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
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: _dataset_payload())},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
        require_complete=True,
    )

    assert summary["status"] == "fail"
    assert summary["completion_status"] == "incomplete"
    assert summary["require_complete"] is True


def test_check_goal_expert_loop_expert_gate_fails_on_remaining_work(monkeypatch):
    check = _load_goal_expert_loop_module()

    monkeypatch.setattr(
        check,
        "_load_sibling_module",
        lambda _filename, module_name: (
            type(
                "FindingsModule",
                (),
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: _dataset_payload())},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
        expert_satisfaction_gate=True,
    )

    assert summary["status"] == "fail"
    assert summary["expert_satisfaction_gate"] is True
    assert summary["require_all_training_ready"] is True
    assert summary["require_complete"] is True
    assert summary["completion_status"] == "incomplete"
    assert summary["layers"]["experiment_design"]["requires_runtime_write"] is True
    assert summary["layers"]["experiment_design"]["runtime_contract"]["status"] == (
        "not_checked"
    )
    text = check.render_text_summary(summary)
    assert (
        "./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py --collection-id col-1 --format messages-jsonl --require-training-ready"
        in text
    )
    assert (
        "./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py --collection-id col-1 --format training-jsonl --require-training-ready"
        in text
    )


def test_check_goal_expert_loop_renders_human_review_summary(monkeypatch):
    check = _load_goal_expert_loop_module()

    monkeypatch.setattr(
        check,
        "_load_sibling_module",
        lambda _filename, module_name: (
            type(
                "FindingsModule",
                (),
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: _dataset_payload())},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
        require_complete=True,
    )
    text = check.render_text_summary(summary)

    assert "Lens expert loop: fail (incomplete)" in text
    assert "review candidates: 2" in text
    assert "How does porosity affect corrosion?" in text
    assert (
        "open: /collections/col-1/objectives/objective-2?review=queue&finding_id=finding-review-1"
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
    assert "Gate diagnosis:" in text
    assert (
        "2 finding(s) still need expert accept, reject, or correct decisions before the dataset can become training-ready."
        in text
    )
    assert (
        "Do not rerun goal analysis for this state; export the decision workspace or browser decision board, fill expert-decision-board.tsv or the JSONL template, then dry-run and import human-confirmed decisions. The browser import can accept a filled TSV board directly."
        in text
    )
    assert "Expert satisfaction: blocked" in text
    assert "- Expert review usable: satisfied" in text
    assert (
        "next: Review candidates are available for human accept, reject, or correct decisions."
        in text
    )
    assert "- Dataset accumulation usable: blocked" in text
    assert (
        "next: Import human-confirmed accept, reject, or correct decisions, then rerun dataset export checks."
        in text
    )
    assert "- Experiment design usable: blocked" in text
    assert "Protocol-ready goals:" in text
    assert "How does preheating affect ductility?" in text
    assert "ai chat: /collections/col-1/assistant?objective_id=objective-1" in text
    assert "review inputs: /collections/col-1/objectives/objective-1?review=training_ready" in text
    assert "Next commands:" in text
    assert (
        "Browser: open the goal review page at "
        "/collections/col-1/objectives/objective-2?review=queue&finding_id=finding-review-1"
        in text
    )
    assert (
        "Browser: download Decision board TSV, fill expert_action/issue_type/"
        "corrected_* columns, paste it into Reviewed decisions, then run Dry run "
        "and Import decisions."
        in text
    )
    assert "Offline CLI:" in text
    assert (
        "./.venv/bin/python scripts/evaluation/expert_gold/prepare_goal_review_workspace.py "
        "--collection-id col-1"
        in text
    )
    assert (
        "./.venv/bin/python scripts/evaluation/expert_gold/merge_expert_decision_board.py "
        "<workspace>/reviewed-findings.template.jsonl "
        "<workspace>/expert-decision-board.tsv --output-path "
        "<workspace>/reviewed-findings.from-board.jsonl"
        in text
    )
    assert (
        "./.venv/bin/python scripts/evaluation/expert_gold/import_goal_review_decisions.py "
        "<workspace>/reviewed-findings.from-board.jsonl --reviewer <human-reviewer> --dry-run "
        "--fail-on-warnings --format text"
        in text
    )
    assert (
        "./.venv/bin/python scripts/evaluation/expert_gold/import_goal_review_decisions.py "
        "<workspace>/reviewed-findings.from-board.jsonl --reviewer <human-reviewer> --format text"
        in text
    )
    assert (
        "./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py --collection-id col-1 --format messages-jsonl --require-training-ready"
        in text
    )
    assert (
        "./.venv/bin/python scripts/evaluation/expert_gold/check_goal_dataset_quality.py --collection-id col-1 --format training-jsonl --require-training-ready"
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
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: dataset)},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
        require_complete=True,
    )

    assert summary["remaining_work"]["pending_goals"] == [
        {
            "objective_id": "objective-2",
            "question": "How does porosity affect corrosion?",
            "review_candidate_count": 0,
            "training_ready_count": 1,
            "training_message_ready_count": 0,
            "protocol_ready_count": 0,
            "next_action": "inspect_training_messages",
            "next_review_action": {},
            "href": "/collections/col-1/objectives/objective-2?review=training_ready",
            "next_review_finding_id": "",
        }
    ]
    text = check.render_text_summary(summary)
    assert (
        "1 goal(s) have training-ready findings but no exportable training messages. "
        "Inspect training-ready samples for missing target fields or evidence text."
    ) in text


def test_check_goal_expert_loop_require_complete_passes_when_no_work_remains(monkeypatch):
    check = _load_goal_expert_loop_module()

    monkeypatch.setattr(
        check,
        "_load_sibling_module",
        lambda _filename, module_name: (
            type(
                "FindingsModule",
                (),
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: _completed_dataset_payload())},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
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
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: _dataset_payload())},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
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
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: dataset)},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
        require_complete=True,
    )

    assert summary["status"] == "fail"
    assert summary["layers"]["experiment_design"]["status"] == "pass"
    assert summary["completion_status"] == "incomplete"
    assert summary["remaining_work"]["pending_goals"] == [
        {
            "objective_id": "objective-2",
            "question": "How does porosity affect corrosion?",
            "review_candidate_count": 0,
            "training_ready_count": 1,
            "training_message_ready_count": 1,
            "protocol_ready_count": 0,
            "next_action": "inspect_protocol_inputs",
            "next_review_action": {},
            "href": "/collections/col-1/objectives/objective-2?review=training_ready",
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
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: dataset)},
            )
        ),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
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
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
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
        lambda _base_url, **_: {
            "/api/v1/collections/{collection_id}/objectives/{objective_id}/analysis": {
                "get": {}
            }
        },
    )
    monkeypatch.setattr(
        check,
        "_local_openapi_paths",
        lambda: _runtime_paths(check),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
        api_base_url="http://localhost:5173",
        require_complete=True,
    )
    text = check.render_text_summary(summary)

    assert summary["status"] == "fail"
    assert summary["completion_status"] == "complete"
    assert summary["layers"]["experiment_design"]["status"] == "fail"
    assert summary["layers"]["experiment_design"]["runtime_contract"]["status"] == "fail"
    diagnostic = summary["layers"]["experiment_design"]["runtime_contract"]["diagnostic"]
    assert diagnostic["code"] == "running_api_not_current_backend"
    assert (
        "Local source app exposes goal-session and experiment-plan routes"
        in diagnostic["detail"]
    )
    assert "runtime write scope: route_contract_only" in text
    assert "copilot save contract: review_gate=protocol_ready_findings" in text
    assert "runtime contract: fail" in text
    assert "runtime diagnostic: running_api_not_current_backend" in text
    assert "missing route: POST /api/v1/goal-sessions" in text
    assert "missing route: POST /api/v1/goal-sessions/{session_id}/messages" in text
    assert (
        "missing route: GET /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans"
        in text
    )
    assert (
        "missing route: POST /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans"
        in text
    )
    assert (
        "missing route: PATCH /api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans/{plan_id}"
        in text
    )


def test_check_goal_expert_loop_passes_when_runtime_plan_routes_exist(monkeypatch):
    check = _load_goal_expert_loop_module()

    monkeypatch.setattr(
        check,
        "_load_sibling_module",
        lambda _filename, module_name: (
            type(
                "FindingsModule",
                (),
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
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
        lambda _base_url, **_: _runtime_paths(check),
    )

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
        api_base_url="http://localhost:5173",
        require_complete=True,
    )

    assert summary["status"] == "pass"
    assert summary["completion_status"] == "complete"
    assert summary["layers"]["experiment_design"]["runtime_contract"]["status"] == "pass"
    assert (
        summary["layers"]["experiment_design"]["runtime_contract"]["runtime_write_check"]
        is False
    )
    assert summary["layers"]["experiment_design"]["runtime_write_scope"] == (
        "route_contract_only"
    )
    assert summary["layers"]["experiment_design"]["copilot_save_contract"] == {
        "review_gate": "protocol_ready_findings",
        "requires_source_message_id": True,
        "requires_collection_grounded_answer": True,
        "requires_auditable_source_links": True,
        "requires_used_evidence_ids": True,
        "requires_protocol_draft_structure": True,
    }


def test_check_goal_expert_loop_runtime_write_check_creates_and_updates_smoke_plan(
    monkeypatch,
):
    check = _load_goal_expert_loop_module()

    monkeypatch.setattr(
        check,
        "_load_sibling_module",
        lambda _filename, module_name: (
            type(
                "FindingsModule",
                (),
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
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
        lambda _base_url, **_: _runtime_paths(check),
    )
    requests: list[tuple[str, str, dict[str, object] | None, str]] = []

    class FakeResponse:
        def __init__(self, payload, *, headers=None):
            self.payload = payload
            self.headers = headers or {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        del timeout
        payload = json.loads(request.data.decode("utf-8")) if request.data else None
        requests.append(
            (
                request.full_url,
                request.get_method(),
                payload,
                request.headers.get("Cookie", ""),
            )
        )
        if request.full_url.endswith("/api/v1/auth/login"):
            return FakeResponse(
                {"user": {"email": "admin@example.com"}},
                headers={"Set-Cookie": "lens_session=session-1; Path=/"},
            )
        if request.get_method() == "POST" and request.full_url.endswith(
            "/api/v1/collections/col-1/objectives/objective-1/experiment-plans"
        ):
            return FakeResponse({"plan_id": "exp_smoke"})
        if request.get_method() == "PATCH" and request.full_url.endswith(
            "/api/v1/collections/col-1/objectives/objective-1/experiment-plans/exp_smoke"
        ):
            return FakeResponse({"plan_id": "exp_smoke", "status": "archived"})
        raise AssertionError(request.full_url)

    monkeypatch.setenv("LENS_CHECK_EMAIL", "admin@example.com")
    monkeypatch.setenv("LENS_CHECK_PASSWORD", "secret")
    monkeypatch.setattr(check.request_url, "urlopen", fake_urlopen)

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
        api_base_url="http://localhost:5173",
        runtime_write_check=True,
        require_complete=True,
    )

    runtime_contract = summary["layers"]["experiment_design"]["runtime_contract"]
    assert summary["status"] == "pass"
    assert summary["layers"]["experiment_design"]["runtime_write_scope"] == (
        "manual_experiment_plan_smoke"
    )
    assert runtime_contract["runtime_write_check"] is True
    assert runtime_contract["checks"][-1] == {
        "name": "write smoke experiment plan",
        "path": "/api/v1/collections/col-1/objectives/objective-1/experiment-plans",
        "method": "post/patch",
        "status": "pass",
        "detail": "created and archived smoke plan",
    }
    assert requests == [
        (
            "http://localhost:5173/api/v1/auth/login",
            "POST",
            {"email": "admin@example.com", "password": "secret"},
            "",
        ),
        (
            "http://localhost:5173/api/v1/collections/col-1/objectives/objective-1/experiment-plans",
            "POST",
            {
                "title": "Lens runtime smoke protocol",
                "content": requests[1][2]["content"],
                "source_links": [],
                "metadata": {"source": "expert_loop_runtime_smoke"},
            },
            "lens_session=session-1",
        ),
        (
            "http://localhost:5173/api/v1/collections/col-1/objectives/objective-1/experiment-plans/exp_smoke",
            "PATCH",
            {
                "title": "Lens runtime smoke protocol",
                "content": requests[2][2]["content"],
                "status": "archived",
            },
            "lens_session=session-1",
        ),
    ]


def test_check_goal_expert_loop_runtime_write_uses_protocol_ready_goal(monkeypatch):
    check = _load_goal_expert_loop_module()
    dataset = _completed_dataset_payload()
    dataset["goals"][0]["protocol_ready_count"] = 0
    write_kwargs = []

    monkeypatch.setattr(
        check,
        "_load_sibling_module",
        lambda _filename, module_name: (
            type(
                "FindingsModule",
                (),
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
            else type(
                "DatasetModule",
                (),
                {"check_goal_dataset_quality": staticmethod(lambda **_: dataset)},
            )
        ),
    )
    monkeypatch.setattr(
        check,
        "_fetch_openapi_paths",
        lambda _base_url, **_: _runtime_paths(check),
    )

    def fake_write_checks(_base_url, **kwargs):
        write_kwargs.append(kwargs)
        return [
            {
                "name": "write smoke experiment plan",
                "path": (
                    f"/api/v1/collections/{kwargs['collection_id']}/objectives/"
                    f"{kwargs['objective_id']}/experiment-plans"
                ),
                "method": "post/patch",
                "status": "pass",
                "detail": "created and archived smoke plan",
            }
        ]

    monkeypatch.setattr(check, "_experiment_plan_write_checks", fake_write_checks)

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
        api_base_url="http://localhost:5173",
        runtime_write_check=True,
    )

    runtime_contract = summary["layers"]["experiment_design"]["runtime_contract"]
    assert write_kwargs == [
        {
            "collection_id": "col-1",
            "objective_id": "objective-2",
            "cookie": "",
        }
    ]
    assert runtime_contract["objective_id"] == "objective-2"
    assert runtime_contract["checks"][-1]["path"] == (
        "/api/v1/collections/col-1/objectives/objective-2/experiment-plans"
    )


def test_check_goal_expert_loop_expert_gate_passes_with_complete_runtime_write(
    monkeypatch,
):
    check = _load_goal_expert_loop_module()

    monkeypatch.setattr(
        check,
        "_load_sibling_module",
        lambda _filename, module_name: (
            type(
                "FindingsModule",
                (),
                {"check_objective_findings_projection": staticmethod(lambda **_: _findings_payload())},
            )
            if module_name == "check_objective_findings_projection"
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
        lambda _base_url, **_: _runtime_paths(check),
    )

    def fake_write_checks(_base_url, **_kwargs):
        return [
            {
                "name": "write smoke experiment plan",
                "path": "/api/v1/collections/col-1/objectives/objective-1/experiment-plans",
                "method": "post/patch",
                "status": "pass",
                "detail": "created and archived smoke plan",
            }
        ]

    monkeypatch.setattr(check, "_experiment_plan_write_checks", fake_write_checks)

    summary = check.check_goal_expert_loop(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2"),
        api_base_url="http://localhost:5173",
        expert_satisfaction_gate=True,
    )

    assert summary["status"] == "pass"
    assert summary["completion_status"] == "complete"
    assert summary["expert_satisfaction_gate"] is True
    assert summary["expert_satisfaction"] == {
        "status": "satisfied",
        "criteria": [
            {
                "key": "expert_review",
                "title": "Expert review usable",
                "requirement": (
                    "Findings are clear, evidence is jumpable, and rows can be "
                    "accepted, rejected, or corrected."
                ),
                "satisfied": True,
                "status": "satisfied",
                "next_step": "Expert review queue is clear.",
            },
            {
                "key": "dataset_accumulation",
                "title": "Dataset accumulation usable",
                "requirement": (
                    "Human labels enter training_ready and exportable messages "
                    "for every checked goal."
                ),
                "satisfied": True,
                "status": "satisfied",
                "next_step": "Training-ready dataset exports are available.",
            },
            {
                "key": "experiment_design",
                "title": "Experiment design usable",
                "requirement": (
                    "Goal Copilot can consume curated Findings and save traceable "
                    "protocol drafts."
                ),
                "satisfied": True,
                "status": "satisfied",
                "next_step": (
                    "Protocol-ready curated Findings and experiment-plan saving "
                    "are available."
                ),
            },
        ],
    }
    assert summary["layers"]["experiment_design"][
        "requires_all_goals_protocol_ready"
    ] is True
    assert summary["layers"]["experiment_design"]["requires_runtime_write"] is True
    assert summary["layers"]["experiment_design"]["runtime_write_scope"] == (
        "manual_experiment_plan_smoke"
    )
    assert summary["layers"]["experiment_design"]["runtime_contract"][
        "runtime_write_check"
    ] is True


def test_check_goal_expert_loop_runtime_write_check_skips_when_routes_are_missing(
    monkeypatch,
):
    check = _load_goal_expert_loop_module()

    monkeypatch.setattr(
        check,
        "_fetch_openapi_paths",
        lambda _base_url, **_: {
            "/api/v1/collections/{collection_id}/objectives/{objective_id}/analysis": {
                "get": {}
            }
        },
    )

    runtime_contract = check._runtime_contract_layer(
        "http://localhost:5173",
        collection_id="col-1",
        objective_id="objective-1",
        runtime_write_check=True,
    )

    assert runtime_contract["status"] == "fail"
    assert runtime_contract["checks"][-1] == {
        "name": "write smoke experiment plan",
        "path": "/api/v1/collections/{collection_id}/objectives/{objective_id}/experiment-plans",
        "method": "post/patch",
        "status": "skipped",
        "detail": "runtime route checks failed; smoke write was not attempted",
    }


def test_check_goal_expert_loop_runtime_write_check_reports_write_failure(
    monkeypatch,
):
    check = _load_goal_expert_loop_module()

    monkeypatch.setattr(
        check,
        "_fetch_openapi_paths",
        lambda _base_url, **_: _runtime_paths(check),
    )

    def fake_urlopen(request, timeout):
        del timeout
        if request.full_url.endswith("/api/v1/auth/login"):
            class LoginResponse:
                headers = {"Set-Cookie": "lens_session=session-1; Path=/"}

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return b"{}"

            return LoginResponse()
        raise HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setenv("LENS_CHECK_EMAIL", "admin@example.com")
    monkeypatch.setenv("LENS_CHECK_PASSWORD", "secret")
    monkeypatch.setattr(check.request_url, "urlopen", fake_urlopen)

    runtime_contract = check._runtime_contract_layer(
        "http://localhost:5173",
        collection_id="col-1",
        objective_id="objective-1",
        runtime_write_check=True,
    )

    assert runtime_contract["status"] == "fail"
    assert runtime_contract["checks"][-1]["status"] == "fail"
    assert "POST /api/v1/collections/col-1/objectives/objective-1/experiment-plans failed" in (
        runtime_contract["checks"][-1]["detail"]
    )
