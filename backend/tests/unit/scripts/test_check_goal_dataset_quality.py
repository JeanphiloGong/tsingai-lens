from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_goal_dataset_check_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "check_goal_dataset_quality.py"
    )
    spec = importlib.util.spec_from_file_location(
        "check_goal_dataset_quality",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _dataset_payload(**overrides):
    item = {
        "sample_id": "sample-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
        "dataset_use_status": "training_ready",
        "trace_status": "evidence_derived",
        "input_blocks": [
            {
                "source_object_id": "ev-1",
                "source_kind": "text",
                "source_ref": "blk-1",
                "text": "Preheating increased ductility by 14%.",
                "href": "/collections/col-1/documents/doc-1?source_ref=blk-1&quote=long-text",
            }
        ],
        "training_evidence_refs": [
            {
                "evidence_ref_id": "ev-1",
                "source_ref": "blk-1",
                "label": "Paper A / p. 4",
                "page": "4",
                "href": "/collections/col-1/documents/doc-1?source_ref=blk-1&quote=long-text",
                "quote": "Preheating increased ductility by 14%.",
            }
        ],
        "expert_target": {
            "source": "curation",
            "statement": "Preheating increased ductility by 14%.",
            "variables": ["preheating"],
            "outcomes": ["ductility"],
            "direction": "increase",
            "scope_summary": "LPBF 316L at 150 C",
            "support_grade": "partial",
            "generalization_status": "paper_level_only",
            "evidence_ref_ids": ["ev-1"],
        },
        "system_prediction": {
            "statement": "Preheating increased ductility by 14%.",
            "variables": ["preheating"],
            "outcomes": ["ductility"],
            "direction": "increase",
            "scope_summary": "LPBF 316L at 150 C",
            "support_grade": "partial",
            "generalization_status": "paper_level_only",
        },
        "training_messages": [
            {
                "role": "user",
                "content": "Extract one evidence-grounded materials finding.",
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "statement": "Preheating increased ductility by 14%.",
                        "variables": ["preheating"],
                        "outcomes": ["ductility"],
                        "direction": "increase",
                        "scope_summary": "LPBF 316L at 150 C",
                        "support_grade": "partial",
                        "generalization_status": "paper_level_only",
                        "evidence_ref_ids": ["ev-1"],
                    },
                    sort_keys=True,
                ),
            },
        ],
    }
    item.update(overrides.pop("item_overrides", {}))
    quality_summary = {
        "by_error_category": {
            "variable_error": 1,
            "evidence_error": 1,
        },
        "by_trace_status": {"evidence_derived": 1},
        "by_review_reason": {"single_paper_evidence": 1},
        "by_system_warning": {"table_row_alignment_uncertain": 1},
        "top_error_categories": [
            {"name": "evidence_error", "count": 1},
            {"name": "variable_error", "count": 1},
        ],
        "top_issue_types": [{"name": "wrong_variable", "count": 1}],
        "top_review_reasons": [{"name": "single_paper_evidence", "count": 1}],
        "top_system_warnings": [
            {"name": "table_row_alignment_uncertain", "count": 1}
        ],
        "by_review_candidate_reason": {},
        "by_review_candidate_warning": {},
        "warning_counts": {
            "unavailable_trace": 0,
            "failed_trace": 0,
        },
    }
    quality_summary.update(overrides.pop("quality_overrides", {}))
    return {
        "scope_id": "goal-1",
        "item_count": 1,
        "quality_summary": quality_summary,
        "items": [item],
        **overrides,
    }


def _failed_check_names(summary):
    return {item["name"] for item in summary["checks"] if item["status"] == "fail"}


def _failed_check(summary, name):
    for item in summary["checks"]:
        if item["name"] == name and item["status"] == "fail":
            return item
    raise AssertionError(f"missing failed check: {name}")


def test_write_stdout_exits_cleanly_on_broken_pipe(monkeypatch):
    check = _load_goal_dataset_check_module()

    class BrokenStdout:
        def write(self, _output):
            raise BrokenPipeError()

        def fileno(self):
            return 1

    monkeypatch.setattr(check.sys, "stdout", BrokenStdout())
    monkeypatch.setattr(check.os, "open", lambda *_args, **_kwargs: 3)
    monkeypatch.setattr(check.os, "dup2", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(check.os, "close", lambda *_args, **_kwargs: None)

    try:
        check.write_stdout("row\n")
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("write_stdout should exit cleanly on BrokenPipeError")


def test_evaluate_goal_dataset_payload_passes_training_ready_sample():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(_dataset_payload())

    assert summary["item_count"] == 1
    assert summary["training_ready_count"] == 1
    assert summary["training_message_ready_count"] == 1
    assert summary["protocol_ready_count"] == 1
    assert summary["by_error_category"] == {
        "variable_error": 1,
        "evidence_error": 1,
    }
    assert summary["top_error_categories"] == [
        {"name": "evidence_error", "count": 1},
        {"name": "variable_error", "count": 1},
    ]
    assert summary["top_issue_types"] == [{"name": "wrong_variable", "count": 1}]
    assert summary["top_review_reasons"] == [
        {"name": "single_paper_evidence", "count": 1}
    ]
    assert summary["top_system_warnings"] == [
        {"name": "table_row_alignment_uncertain", "count": 1}
    ]
    assert summary["by_review_reason"] == {"single_paper_evidence": 1}
    assert summary["by_system_warning"] == {"table_row_alignment_uncertain": 1}
    assert summary["by_review_candidate_reason"] == {}
    assert summary["by_review_candidate_warning"] == {}
    assert all(item["status"] == "pass" for item in summary["checks"])


def test_evaluate_goal_dataset_payload_accepts_review_candidate_sample():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(
            item_overrides={
                "dataset_use_status": "review_candidate",
                "expert_target": None,
            }
        )
    )

    assert summary["review_candidate_count"] == 1
    assert "dataset has at least one active sample" not in _failed_check_names(summary)
    check_names = {item["name"] for item in summary["checks"]}
    assert "dataset has at least one training-ready sample" not in check_names


def test_build_goal_review_packet_lists_candidate_evidence():
    check = _load_goal_dataset_check_module()

    dataset = _dataset_payload(
        item_overrides={
            "dataset_use_status": "review_candidate",
            "presentation_bucket": "review_queue",
            "trace_status": "evidence_derived",
            "system_prediction": {
                "statement": "Preheating increased ductility by 14%.",
                "variables": ["preheating"],
                "outcomes": ["ductility"],
                "direction": "increase",
                "scope_summary": "LPBF 316L at 150 C",
                "support_grade": "strong",
                "review_status": "needs_review",
                "review_reasons": ["single_paper_evidence", "table_row_needs_expert_review"],
                "warnings": [],
            },
            "review_action": {
                "code": "review_table_rows",
                "label": "review selected table rows before accepting or correcting",
            },
            "expert_target": {
                "source": "ai_review_feedback",
                "statement": "Preheating increased ductility by 14%.",
                "review_status": "correct",
                "note": "AI suggestion; human review still required.",
            },
        }
    )

    packet = check.build_goal_review_packet(dataset, collection_id="col-1")
    text = check.render_review_packet_summary(
        {"status": "pass", "collection_id": "col-1", "goals": [{"review_packet": packet}]}
    )

    assert packet["candidate_count"] == 1
    candidate = packet["candidates"][0]
    assert candidate["statement"] == "Preheating increased ductility by 14%."
    assert candidate["claim_id"] == "claim-1"
    assert candidate["variables"] == ["preheating"]
    assert candidate["review_reasons"] == [
        "single_paper_evidence",
        "table_row_needs_expert_review",
    ]
    assert candidate["warnings"] == []
    assert (
        candidate["recommended_action"]
        == "review selected table rows before accepting or correcting"
    )
    assert candidate["recommended_action_code"] == "review_table_rows"
    assert candidate["protocol_readiness"] == {
        "status": "ready_after_review",
        "ready_after_review": True,
        "missing": ["expert_review_decision"],
        "blocking_missing": [],
        "checks": {
            "expert_review_decision": False,
            "training_messages": True,
            "statement": True,
            "variables": True,
            "outcomes": True,
            "direction_or_scope": True,
            "support_status": True,
            "support_grade": True,
            "traceable_training_evidence": True,
        },
        "guidance": "Accept only after expert review confirms the finding and evidence.",
    }
    assert packet["risk_summary"] == {
        "action:review_table_rows": 1,
        "reason:single_paper_evidence": 1,
        "reason:table_row_needs_expert_review": 1,
    }
    assert packet["goal_id"] == "goal-1"
    assert (
        candidate["open_url"]
        == "/collections/col-1/goals/goal-1?review=queue&finding_id=finding-1"
    )
    assert candidate["evidence"][0]["quote"] == "Preheating increased ductility by 14%."
    assert candidate["evidence"][0]["evidence_ref_id"] == "ev-1"
    assert (
        candidate["evidence"][0]["href"]
        == "/collections/col-1/documents/doc-1?source_ref=blk-1&quote=long-text"
    )
    assert "Goal goal-1: 1 review candidate(s)" in text
    assert (
        "open finding: /collections/col-1/goals/goal-1?review=queue&finding_id=finding-1"
        in text
    )
    assert "fields: variables=preheating; outcomes=ductility; direction=increase" in text
    assert (
        "recommended action: review selected table rows before accepting or correcting"
        in text
    )
    assert (
        "Risk summary: action:review_table_rows=1, reason:single_paper_evidence=1, "
        "reason:table_row_needs_expert_review=1"
    ) in text
    assert "review reasons: single_paper_evidence, table_row_needs_expert_review" in text
    assert "protocol readiness: ready_after_review" in text
    assert "Paper A / p. 4 / p. 4" not in text
    assert "AI suggestion; human review still required." in text
    assert "open: /collections/col-1/documents/doc-1?source_ref=blk-1" in text
    assert "quote=long-text" not in text

    summary = check.evaluate_goal_dataset_payload(dataset)
    assert summary["next_review_finding_id"] == "finding-1"
    assert summary["next_review_action"] == {
        "code": "review_table_rows",
        "label": "review selected table rows before accepting or correcting",
    }


def test_render_review_jsonl_exports_candidate_rows():
    check = _load_goal_dataset_check_module()

    dataset = _dataset_payload(
        item_overrides={
            "dataset_use_status": "review_candidate",
            "presentation_bucket": "review_queue",
            "trace_status": "evidence_derived",
            "system_prediction": {
                "statement": "Preheating increased ductility by 14%.",
                "variables": ["preheating"],
                "mediators": ["grain refinement"],
                "outcomes": ["ductility"],
                "direction": "increase",
                "scope_summary": "LPBF 316L at 150 C",
                "support_grade": "strong",
                "review_status": "needs_review",
                "review_reasons": ["single_paper_evidence"],
                "warnings": ["needs_expert_review"],
            },
            "review_action": {
                "code": "accept_as_paper_level",
                "label": "accept only as paper-level evidence unless another paper confirms it",
            },
            "expert_target": {
                "source": "ai_review_feedback",
                "statement": "Preheating increased ductility by 14%.",
                "review_status": "correct",
                "note": "AI suggestion; human review still required.",
            },
        }
    )
    packet = check.build_goal_review_packet(dataset, collection_id="col-1")

    body = check.render_review_jsonl_summary(
        {"status": "pass", "collection_id": "col-1", "goals": [{"review_packet": packet}]}
    )
    rows = [json.loads(line) for line in body.splitlines()]

    assert len(rows) == 1
    assert rows[0]["collection_id"] == "col-1"
    assert rows[0]["goal_id"] == "goal-1"
    assert rows[0]["finding_id"] == "finding-1"
    assert rows[0]["claim_id"] == "claim-1"
    assert rows[0]["statement"] == "Preheating increased ductility by 14%."
    assert rows[0]["variables"] == ["preheating"]
    assert rows[0]["mediators"] == ["grain refinement"]
    assert rows[0]["outcomes"] == ["ductility"]
    assert rows[0]["recommended_action_code"] == "accept_as_paper_level"
    assert rows[0]["review_instructions"].startswith("Set action=accept")
    assert rows[0]["review_risk_flags"] == [
        "Paper-level evidence; do not treat as cross-paper conclusion without confirmation."
    ]
    assert rows[0]["protocol_readiness"]["status"] == "ready_after_review"
    assert rows[0]["protocol_readiness"]["missing"] == ["expert_review_decision"]
    assert rows[0]["protocol_readiness"]["blocking_missing"] == []
    assert rows[0]["protocol_readiness"]["checks"]["variables"] is True
    assert rows[0]["action"] == "skip"
    assert rows[0]["allowed_actions"] == ["accept", "reject", "correct", "skip"]
    assert "wrong_direction" in rows[0]["reject_issue_options"]
    assert rows[0]["expert_note"] == ""
    assert rows[0]["suggested_target"]["review_status"] == "correct"
    assert (
        rows[0]["evidence"][0]["href"]
        == "/collections/col-1/documents/doc-1?source_ref=blk-1&quote=long-text"
    )


def test_render_decision_template_exports_editable_import_rows():
    check = _load_goal_dataset_check_module()

    dataset = _dataset_payload(
        item_overrides={
            "dataset_use_status": "review_candidate",
            "presentation_bucket": "review_queue",
            "trace_status": "evidence_derived",
            "system_prediction": {
                "statement": "Preheating increased ductility by 14%.",
                "variables": ["preheating"],
                "mediators": ["grain refinement"],
                "outcomes": ["ductility"],
                "direction": "increase",
                "scope_summary": "LPBF 316L at 150 C",
                "support_grade": "strong",
                "review_status": "needs_review",
                "review_reasons": ["single_paper_evidence"],
            },
            "review_action": {
                "code": "accept_as_paper_level",
                "label": "accept only as paper-level evidence unless another paper confirms it",
            },
            "expert_target": {},
        }
    )
    packet = check.build_goal_review_packet(dataset, collection_id="col-1")

    body = check.render_decision_template_summary(
        {"status": "pass", "collection_id": "col-1", "goals": [{"review_packet": packet}]}
    )
    rows = [json.loads(line) for line in body.splitlines()]

    assert len(rows) == 1
    assert rows[0] == {
        "collection_id": "col-1",
        "goal_id": "goal-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
        "action": "skip",
        "issue_type": "",
        "expert_note": "",
        "statement": "Preheating increased ductility by 14%.",
        "variables": ["preheating"],
        "outcomes": ["ductility"],
        "direction": "increase",
        "support_grade": "strong",
        "recommended_action_code": "accept_as_paper_level",
        "review_reasons": ["single_paper_evidence"],
        "protocol_blocking_missing": [],
        "curated_evidence_ref_ids": ["ev-1"],
        "suggested_target": {
            "statement": "Preheating increased ductility by 14%.",
            "status": "limited",
            "support_grade": "strong",
            "review_status": "accepted",
            "variables": ["preheating"],
            "mediators": ["grain refinement"],
            "outcomes": ["ductility"],
            "direction": "increase",
            "scope_summary": "LPBF 316L at 150 C",
            "evidence_ref_ids": ["ev-1"],
        },
    }


def test_render_messages_jsonl_exports_training_ready_messages():
    check = _load_goal_dataset_check_module()

    export = check.build_goal_training_message_export(_dataset_payload())
    body = check.render_messages_jsonl_summary({"goals": [{"training_export": export}]})
    rows = [json.loads(line) for line in body.splitlines()]

    assert export["row_count"] == 1
    assert rows[0]["messages"][0] == {
        "role": "user",
        "content": "Extract one evidence-grounded materials finding.",
    }
    assistant_payload = json.loads(rows[0]["messages"][1]["content"])
    assert assistant_payload == {
        "direction": "increase",
        "evidence_ref_ids": ["ev-1"],
        "generalization_status": "paper_level_only",
        "outcomes": ["ductility"],
        "scope_summary": "LPBF 316L at 150 C",
        "statement": "Preheating increased ductility by 14%.",
        "support_grade": "partial",
        "variables": ["preheating"],
    }
    assert "metadata" not in rows[0]


def test_render_training_jsonl_exports_messages_with_traceable_metadata():
    check = _load_goal_dataset_check_module()

    dataset = _dataset_payload(collection_id="col-1", scope_type="goal")
    export = check.build_goal_training_message_export(
        dataset,
        include_metadata=True,
    )
    body = check.render_training_jsonl_summary(
        {"goals": [{"training_export": export}]}
    )
    rows = [json.loads(line) for line in body.splitlines()]

    assert export["row_count"] == 1
    assert rows[0]["messages"][0]["role"] == "user"
    assert rows[0]["metadata"] == {
        "collection_id": "col-1",
        "scope_type": "goal",
        "goal_id": "goal-1",
        "sample_id": "sample-1",
        "finding_id": "finding-1",
        "claim_id": "claim-1",
        "label_status": "",
        "dataset_use_status": "training_ready",
        "trace_status": "evidence_derived",
        "reviewer": "",
        "review_status": "",
        "issue_type": "",
        "support_grade": "partial",
        "generalization_status": "paper_level_only",
        "evidence_ref_ids": ["ev-1"],
    }


def test_check_goal_dataset_quality_includes_training_metadata_when_requested(
    monkeypatch,
):
    check = _load_goal_dataset_check_module()
    monkeypatch.setattr(
        check,
        "_local_goal_dataset",
        lambda collection_id, goal_id: _dataset_payload(
            collection_id=collection_id,
            scope_id=goal_id,
            scope_type="goal",
        ),
    )

    summary = check.check_goal_dataset_quality(
        collection_id="col-1",
        goal_ids=("goal-1",),
        include_training_export=True,
        include_training_metadata=True,
    )
    body = check.render_training_jsonl_summary(summary)
    rows = [json.loads(line) for line in body.splitlines()]

    assert summary["goals"][0]["training_export"]["row_count"] == 1
    assert rows[0]["metadata"]["collection_id"] == "col-1"
    assert rows[0]["metadata"]["goal_id"] == "goal-1"
    assert rows[0]["metadata"]["claim_id"] == "claim-1"


def test_build_goal_review_packet_marks_protocol_blocking_gaps():
    check = _load_goal_dataset_check_module()

    dataset = _dataset_payload(
        item_overrides={
            "dataset_use_status": "review_candidate",
            "expert_target": None,
            "system_prediction": {
                "statement": "Preheating increased ductility by 14%.",
                "variables": [],
                "outcomes": ["ductility"],
                "direction": "",
                "scope_summary": "",
                "support_grade": "strong",
                "review_status": "needs_review",
            },
        }
    )

    packet = check.build_goal_review_packet(dataset, collection_id="col-1")
    candidate = packet["candidates"][0]
    text = check.render_review_packet_summary(
        {"status": "pass", "collection_id": "col-1", "goals": [{"review_packet": packet}]}
    )

    assert candidate["protocol_readiness"]["status"] == "needs_correction"
    assert candidate["protocol_readiness"]["ready_after_review"] is False
    assert candidate["protocol_readiness"]["blocking_missing"] == [
        "variables",
        "direction_or_scope",
    ]
    assert (
        "protocol readiness gaps: variables, direction_or_scope"
        in text
    )


def test_render_messages_jsonl_skips_review_candidates():
    check = _load_goal_dataset_check_module()

    export = check.build_goal_training_message_export(
        _dataset_payload(
            item_overrides={
                "dataset_use_status": "review_candidate",
                "expert_target": None,
                "training_messages": [],
            }
        )
    )

    assert export["row_count"] == 0
    assert check.render_messages_jsonl_summary({"goals": [{"training_export": export}]}) == ""


def test_evaluate_goal_dataset_payload_requires_training_ready_when_requested():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(
            item_overrides={
                "dataset_use_status": "review_candidate",
                "expert_target": None,
            }
        ),
        require_training_ready=True,
    )

    assert "dataset has at least one training-ready sample" in _failed_check_names(
        summary
    )


def test_evaluate_goal_dataset_payload_fails_without_active_sample():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(
            item_overrides={
                "dataset_use_status": "rejected",
                "expert_target": None,
            }
        )
    )

    assert "dataset has at least one active sample" in _failed_check_names(summary)


def test_evaluate_goal_dataset_payload_fails_failed_or_unavailable_trace_warning():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(
            quality_overrides={
                "warning_counts": {
                    "unavailable_trace": 1,
                    "failed_trace": 1,
                }
            }
        )
    )

    assert "dataset has no unavailable or failed traces" in _failed_check_names(summary)


def test_evaluate_goal_dataset_payload_fails_missing_text_input_blocks():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(
            item_overrides={
                "input_blocks": [
                    {
                        "source_object_id": "oeu-1",
                        "source_kind": "objective_evidence_unit",
                    }
                ]
            }
        )
    )

    assert "active samples include text input blocks" in _failed_check_names(summary)


def test_evaluate_goal_dataset_payload_fails_missing_traceable_training_evidence():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(
            item_overrides={
                "training_evidence_refs": [
                    {
                        "evidence_ref_id": "ev-1",
                        "source_ref": "blk-1",
                        "quote": "Preheating increased ductility by 14%.",
                    }
                ]
            }
        )
    )

    assert (
        "active samples include traceable training evidence"
        in _failed_check_names(summary)
    )


def test_evaluate_goal_dataset_payload_fails_missing_training_messages():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(item_overrides={"training_messages": []})
    )

    assert "training-ready samples include fine-tuning messages" in _failed_check_names(
        summary
    )
    assert "missing_message_pair" in _failed_check(
        summary,
        "training-ready samples include fine-tuning messages",
    )["detail"]


def test_evaluate_goal_dataset_payload_fails_missing_protocol_inputs():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(
            item_overrides={
                "expert_target": {
                    "source": "curation",
                    "statement": "Preheating increased ductility by 14%.",
                    "variables": [],
                    "outcomes": ["ductility"],
                    "direction": "increase",
                    "scope_summary": "LPBF 316L at 150 C",
                    "support_grade": "partial",
                    "generalization_status": "paper_level_only",
                    "evidence_ref_ids": ["ev-1"],
                },
                "system_prediction": {
                    "statement": "Preheating increased ductility by 14%.",
                    "variables": [],
                    "outcomes": ["ductility"],
                    "direction": "increase",
                    "scope_summary": "LPBF 316L at 150 C",
                    "support_grade": "partial",
                    "generalization_status": "paper_level_only",
                }
            }
        )
    )

    assert summary["protocol_ready_count"] == 0
    assert "training-ready samples include protocol design inputs" in _failed_check_names(
        summary
    )


def test_evaluate_goal_dataset_payload_fails_mismatched_training_message_target():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(
            item_overrides={
                "training_messages": [
                    {
                        "role": "user",
                        "content": "Extract one evidence-grounded materials finding.",
                    },
                    {
                        "role": "assistant",
                        "content": '{"statement": "System prediction, not expert target."}',
                    },
                ]
            }
        )
    )

    assert "training-ready samples include fine-tuning messages" in _failed_check_names(
        summary
    )
    assert "mismatched_assistant_generalization_status" in _failed_check(
        summary,
        "training-ready samples include fine-tuning messages",
    )["detail"]


def test_evaluate_goal_dataset_payload_fails_training_message_without_scope_boundary():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(
            item_overrides={
                "training_messages": [
                    {
                        "role": "user",
                        "content": "Extract one evidence-grounded materials finding.",
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "statement": "Preheating increased ductility by 14%.",
                                "variables": ["preheating"],
                                "outcomes": ["ductility"],
                                "direction": "increase",
                                "scope_summary": "LPBF 316L at 150 C",
                                "support_grade": "partial",
                                "evidence_ref_ids": ["ev-1"],
                            },
                            sort_keys=True,
                        ),
                    },
                ]
            }
        )
    )

    assert "training-ready samples include fine-tuning messages" in _failed_check_names(
        summary
    )
