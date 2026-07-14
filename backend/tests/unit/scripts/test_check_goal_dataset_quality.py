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
        "dataset_use_status": "training_ready",
        "trace_status": "evidence_derived",
        "input_blocks": [
            {
                "source_object_id": "ev-1",
                "source_kind": "text",
                "source_ref": "blk-1",
                "text": "Preheating increased ductility by 14%.",
                "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
            }
        ],
        "training_evidence_refs": [
            {
                "evidence_ref_id": "ev-1",
                "source_ref": "blk-1",
                "label": "Paper A / p. 4",
                "page": "4",
                "href": "/collections/col-1/documents/doc-1?source_ref=blk-1",
                "quote": "Preheating increased ductility by 14%.",
            }
        ],
        "expert_target": {
            "source": "curation",
            "statement": "Preheating increased ductility by 14%.",
        },
        "system_prediction": {
            "statement": "Preheating increased ductility by 14%.",
            "variables": ["preheating"],
            "outcomes": ["ductility"],
            "direction": "increase",
            "scope_summary": "LPBF 316L at 150 C",
        },
        "training_messages": [
            {
                "role": "user",
                "content": "Extract one evidence-grounded materials finding.",
            },
            {
                "role": "assistant",
                "content": '{"statement": "Preheating increased ductility by 14%."}',
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
    assert packet["goal_id"] == "goal-1"
    assert (
        candidate["open_url"]
        == "/collections/col-1/goals/goal-1?review=queue&finding_id=finding-1"
    )
    assert candidate["evidence"][0]["quote"] == "Preheating increased ductility by 14%."
    assert candidate["evidence"][0]["evidence_ref_id"] == "ev-1"
    assert candidate["evidence"][0]["href"] == "/collections/col-1/documents/doc-1?source_ref=blk-1"
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
    assert "review reasons: single_paper_evidence, table_row_needs_expert_review" in text
    assert "Paper A / p. 4 / p. 4" not in text
    assert "AI suggestion; human review still required." in text
    assert "open: /collections/col-1/documents/doc-1?source_ref=blk-1" in text

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
    assert rows[0]["statement"] == "Preheating increased ductility by 14%."
    assert rows[0]["variables"] == ["preheating"]
    assert rows[0]["mediators"] == ["grain refinement"]
    assert rows[0]["outcomes"] == ["ductility"]
    assert rows[0]["recommended_action_code"] == "accept_as_paper_level"
    assert rows[0]["action"] == "skip"
    assert rows[0]["allowed_actions"] == ["accept", "reject", "correct", "skip"]
    assert "wrong_direction" in rows[0]["reject_issue_options"]
    assert rows[0]["expert_note"] == ""
    assert rows[0]["suggested_target"]["review_status"] == "correct"
    assert rows[0]["evidence"][0]["href"] == "/collections/col-1/documents/doc-1?source_ref=blk-1"


def test_render_messages_jsonl_exports_training_ready_messages():
    check = _load_goal_dataset_check_module()

    export = check.build_goal_training_message_export(_dataset_payload())
    body = check.render_messages_jsonl_summary({"goals": [{"training_export": export}]})
    rows = [json.loads(line) for line in body.splitlines()]

    assert export["row_count"] == 1
    assert rows == [
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Extract one evidence-grounded materials finding.",
                },
                {
                    "role": "assistant",
                    "content": '{"statement": "Preheating increased ductility by 14%."}',
                },
            ]
        }
    ]


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


def test_evaluate_goal_dataset_payload_fails_missing_protocol_inputs():
    check = _load_goal_dataset_check_module()

    summary = check.evaluate_goal_dataset_payload(
        _dataset_payload(
            item_overrides={
                "system_prediction": {
                    "statement": "Preheating increased ductility by 14%.",
                    "variables": [],
                    "outcomes": ["ductility"],
                    "direction": "increase",
                    "scope_summary": "LPBF 316L at 150 C",
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
