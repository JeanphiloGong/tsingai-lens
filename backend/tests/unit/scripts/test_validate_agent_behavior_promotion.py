from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


def _load_gate_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "agent_behavior_promotion"
        / "validate_promotion_record.py"
    )
    spec = importlib.util.spec_from_file_location(
        "validate_agent_behavior_promotion",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _artifact(tmp_path: Path, name: str, payload: dict) -> dict[str, str]:
    path = tmp_path / name
    content = json.dumps(payload, sort_keys=True).encode("utf-8")
    path.write_bytes(content)
    return {
        "path": name,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _fingerprint(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _evaluation(
    tmp_path: Path,
    *,
    name: str,
    papers: list[str],
) -> dict:
    cohort = "expert_gold" if name == "gold" else "fresh_papers"
    sealed_at = (
        "2026-08-31T00:00:00Z" if cohort == "expert_gold" else "2026-09-01T18:00:00Z"
    )
    return {
        "run_id": f"run-{name}",
        "started_at": "2026-09-02T00:00:00Z",
        "completed_at": "2026-09-02T00:05:00Z",
        "implementation_revision": "a" * 40,
        "runtime_contract_fingerprint": _fingerprint("runtime-contract-v1"),
        "model": "test-model-v1",
        "dataset": {
            "dataset_id": f"dataset-{name}",
            "dataset_version": "1",
            "cohort": cohort,
            "sealed_at": sealed_at,
            "artifact": _artifact(
                tmp_path,
                f"{name}-dataset.json",
                {"papers": papers},
            ),
        },
        "trajectory_artifact": _artifact(
            tmp_path,
            f"{name}-trajectory.json",
            {"tool_calls": [f"call-{name}"]},
        ),
        "evaluation_report_artifact": _artifact(
            tmp_path,
            f"{name}-report.json",
            {"status": "reviewed"},
        ),
        "paper_fingerprints": papers,
        "metrics": {
            "expected_relevant_items": 10,
            "recalled_relevant_items": 9,
            "evaluated_decisions": 10,
            "scientific_errors": 0,
            "technical_failures": 0,
            "input_tokens": 1_000,
            "output_tokens": 200,
            "model_calls": 4,
            "unreported_model_calls": 0,
        },
        "expert_review": {
            "reviewer_id": "materials-expert@example.com",
            "reviewed_at": "2026-09-02T00:10:00Z",
            "decision": "accepted",
            "artifact": _artifact(
                tmp_path,
                f"{name}-review.json",
                {"decision": "accepted"},
            ),
        },
    }


def _record(tmp_path: Path) -> dict:
    return {
        "schema_version": "agent_behavior_promotion.v1",
        "candidate": {
            "behavior_id": "resolve-paper-local-group-definitions",
            "behavior_version": "1",
            "research_action": (
                "When a result uses an undefined group label, inspect the same "
                "paper's Methods for its definition before binding the result."
            ),
            "scientific_invariant": (
                "A group definition and result remain separate source-local facts."
            ),
            "target_fast_path_stage": "objective_evidence_extraction",
            "excluded_shortcuts": [
                "Do not encode a paper-local label as a global alias."
            ],
        },
        "origin_trajectory": {
            "recorded_at": "2026-09-01T00:00:00Z",
            "artifact": _artifact(
                tmp_path,
                "origin-trajectory.json",
                {"tool_calls": ["call-origin"], "evidence": ["evidence-origin"]},
            ),
            "paper_fingerprints": [_fingerprint("development-paper")],
            "tool_call_ids": ["call-origin"],
            "source_refs": ["doc-1:text_window:window-7"],
            "evidence_ids": ["evidence-origin"],
            "judgment_refs": ["judgment-origin"],
        },
        "acceptance_bounds": {
            "approved_by": "research-lead@example.com",
            "approved_at": "2026-09-01T12:00:00Z",
            "minimum_expert_gold_papers": 2,
            "minimum_fresh_papers": 2,
            "minimum_recall": 0.8,
            "maximum_scientific_error_rate": 0.05,
            "maximum_technical_failure_rate": 0.1,
            "maximum_total_tokens_per_paper": 1_000,
            "maximum_model_calls_per_paper": 3,
        },
        "evaluations": {
            "expert_gold": _evaluation(
                tmp_path,
                name="gold",
                papers=[_fingerprint("gold-1"), _fingerprint("gold-2")],
            ),
            "fresh_papers": _evaluation(
                tmp_path,
                name="fresh",
                papers=[_fingerprint("fresh-1"), _fingerprint("fresh-2")],
            ),
        },
        "promotion_request": {
            "requested_by": "maintainer@example.com",
            "requested_at": "2026-09-03T00:00:00Z",
            "target": "fast_path",
        },
    }


def _write_record(tmp_path: Path, record: dict) -> Path:
    path = tmp_path / "promotion-record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_complete_gold_and_fresh_evidence_is_eligible_for_maintainer_review(
    tmp_path,
):
    module = _load_gate_module()
    record_path = _write_record(tmp_path, _record(tmp_path))

    result = module.evaluate_promotion_record(record_path)

    assert result["schema_version"] == "agent_behavior_promotion_evaluation.v1"
    assert result["verdict"] == "eligible_for_maintainer_review"
    assert result["promotion_applied"] is False
    assert result["blocking_reasons"] == []
    assert result["cohorts"]["expert_gold"]["observed"] == {
        "paper_count": 2,
        "recall": 0.9,
        "scientific_error_rate": 0.0,
        "technical_failure_rate": 0.0,
        "total_tokens_per_paper": 600.0,
        "model_calls_per_paper": 2.0,
    }
    assert result["cohorts"]["fresh_papers"]["status"] == "pass"
    assert result["next_action"] == (
        "A maintainer may review the generalized behavior and its implementation; "
        "this gate does not modify Fast Path."
    )


def test_missing_fresh_paper_evaluation_is_an_invalid_record(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    del record["evaluations"]["fresh_papers"]
    record_path = _write_record(tmp_path, record)

    with pytest.raises(module.PromotionRecordError, match="fresh_papers"):
        module.evaluate_promotion_record(record_path)


def test_gold_and_fresh_papers_must_be_independent(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["fresh_papers"]["paper_fingerprints"][0] = record[
        "evaluations"
    ]["expert_gold"]["paper_fingerprints"][0]
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "fresh_papers_overlap_expert_gold"
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("implementation_revision", "b" * 40),
        ("runtime_contract_fingerprint", _fingerprint("other-runtime")),
        ("model", "other-model-v1"),
    ],
)
def test_gold_and_fresh_runs_must_replay_the_same_behavior(
    tmp_path,
    field,
    value,
):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["fresh_papers"][field] = value
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "evaluation_runtime_mismatch"
    ]


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("recalled_relevant_items", 7, "recall_below_minimum"),
        ("scientific_errors", 1, "scientific_error_rate_above_maximum"),
        ("technical_failures", 1, "technical_failure_rate_above_maximum"),
        ("input_tokens", 2_000, "total_tokens_per_paper_above_maximum"),
        ("model_calls", 7, "model_calls_per_paper_above_maximum"),
    ],
)
def test_each_preregistered_boundary_blocks_promotion(
    tmp_path,
    field,
    value,
    expected_code,
):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["fresh_papers"]["metrics"][field] = value
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert expected_code in [reason["code"] for reason in result["blocking_reasons"]]


def test_tampered_evaluation_artifact_blocks_promotion(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record_path = _write_record(tmp_path, record)
    (tmp_path / "fresh-report.json").write_text(
        '{"status":"changed after review"}',
        encoding="utf-8",
    )

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "artifact_digest_mismatch"
    ]
    assert result["blocking_reasons"][0]["path"] == (
        "evaluations.fresh_papers.evaluation_report_artifact"
    )


def test_boundaries_must_be_approved_before_evaluation_begins(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["acceptance_bounds"]["approved_at"] = "2026-09-02T00:01:00Z"
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "acceptance_bounds_not_preregistered"
    ]


def test_fresh_papers_must_not_include_behavior_development_papers(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["fresh_papers"]["paper_fingerprints"][0] = record[
        "origin_trajectory"
    ]["paper_fingerprints"][0]
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "fresh_papers_overlap_development_papers"
    ]


def test_schema_is_machine_readable_and_forbids_manual_verdicts():
    module = _load_gate_module()

    schema = module.promotion_record_json_schema()

    assert schema["properties"]["schema_version"]["const"] == (
        "agent_behavior_promotion.v1"
    )
    assert schema["additionalProperties"] is False
    assert "verdict" not in schema["properties"]


def test_record_model_does_not_accept_a_manual_promotion_status(tmp_path):
    module = _load_gate_module()
    record = deepcopy(_record(tmp_path))
    record["promotion_status"] = "promoted"
    record_path = _write_record(tmp_path, record)

    with pytest.raises(module.PromotionRecordError, match="promotion_status"):
        module.evaluate_promotion_record(record_path)


def test_promotion_request_cannot_precede_completed_human_review(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["promotion_request"]["requested_at"] = "2026-09-02T00:07:00Z"
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "promotion_requested_before_human_review"
    ]


def test_nonaccepted_human_review_blocks_promotion(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["fresh_papers"]["expert_review"][
        "decision"
    ] = "needs_revision"
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "human_review_not_accepted"
    ]


@pytest.mark.parametrize(
    ("path", "identity"),
    [
        (("acceptance_bounds", "approved_by"), "agent-research-lead"),
        (
            ("evaluations", "expert_gold", "expert_review", "reviewer_id"),
            "ai-reviewer-gold",
        ),
        (("promotion_request", "requested_by"), "agent-release-manager"),
    ],
)
def test_agent_identity_cannot_fill_a_human_gate_role(tmp_path, path, identity):
    module = _load_gate_module()
    record = _record(tmp_path)
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = identity
    record_path = _write_record(tmp_path, record)

    with pytest.raises(module.PromotionRecordError, match="human expert id"):
        module.evaluate_promotion_record(record_path)


def test_invalid_metric_counts_are_rejected_before_scoring(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["expert_gold"]["metrics"]["recalled_relevant_items"] = 11
    record_path = _write_record(tmp_path, record)

    with pytest.raises(
        module.PromotionRecordError,
        match="recalled_relevant_items",
    ):
        module.evaluate_promotion_record(record_path)


def test_missing_artifact_blocks_promotion_without_hiding_other_metrics(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["fresh_papers"]["trajectory_artifact"][
        "path"
    ] = "missing-trajectory.json"
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "artifact_missing"
    ]
    assert result["cohorts"]["fresh_papers"]["status"] == "fail"
    assert result["cohorts"]["fresh_papers"]["observed"]["recall"] == 0.9


def test_unreported_model_usage_blocks_cost_evaluation(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["fresh_papers"]["metrics"]["unreported_model_calls"] = 1
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "cost_observation_incomplete"
    ]


def test_gate_uses_exact_metric_ratio_instead_of_rounded_display_value(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    metrics = record["evaluations"]["fresh_papers"]["metrics"]
    metrics["expected_relevant_items"] = 100_000
    metrics["recalled_relevant_items"] = 79_996
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert "recall_below_minimum" in [
        reason["code"] for reason in result["blocking_reasons"]
    ]


def test_expert_gold_must_be_frozen_before_the_origin_trajectory(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["expert_gold"]["dataset"][
        "sealed_at"
    ] = "2026-09-01T01:00:00Z"
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "expert_gold_not_fixed_before_behavior"
    ]


def test_each_dataset_must_be_sealed_before_its_evaluation_starts(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["fresh_papers"]["dataset"][
        "sealed_at"
    ] = "2026-09-02T00:01:00Z"
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "dataset_not_sealed_before_evaluation"
    ]


def test_dataset_cohort_identity_cannot_be_relabelled(tmp_path):
    module = _load_gate_module()
    record = _record(tmp_path)
    record["evaluations"]["fresh_papers"]["dataset"]["cohort"] = "expert_gold"
    record_path = _write_record(tmp_path, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "dataset_cohort_mismatch"
    ]


def test_artifact_symlink_cannot_escape_the_record_directory(tmp_path):
    module = _load_gate_module()
    record_dir = tmp_path / "record"
    record_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"private":"not promotion evidence"}', encoding="utf-8")
    linked = record_dir / "linked-report.json"
    linked.symlink_to(outside)
    record = _record(record_dir)
    record["evaluations"]["fresh_papers"]["evaluation_report_artifact"] = {
        "path": linked.name,
        "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
    }
    record_path = _write_record(record_dir, record)

    result = module.evaluate_promotion_record(record_path)

    assert result["verdict"] == "blocked"
    assert [reason["code"] for reason in result["blocking_reasons"]] == [
        "artifact_outside_record_directory"
    ]


def test_generated_report_records_utc_evaluation_time(tmp_path):
    module = _load_gate_module()
    record_path = _write_record(tmp_path, _record(tmp_path))

    result = module.evaluate_promotion_record(record_path)

    evaluated_at = datetime.fromisoformat(result["evaluated_at"])
    assert evaluated_at.tzinfo == timezone.utc
