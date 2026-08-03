from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


DIRECT_SOURCE_TEXT = (
    "Relative density increased from 95.4% for low VED 70 J/mm3 "
    "to 99.6% for high VED 100 J/mm3."
)


def _load_module():
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts/evaluation/expert_gold/check_objective_findings_projection.py"
    )
    spec = importlib.util.spec_from_file_location(
        "check_objective_findings_projection", script
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _failure_modes() -> dict:
    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )
    return json.loads(fixture.read_text(encoding="utf-8"))["failure_modes"]


def _bundle(*, synthesis_status: str = "insufficient_confirmation"):
    finding = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 2,
        "finding_id": "finding-1",
        "statement": "Higher VED was associated with higher relative density.",
        "factors": ["volumetric energy density"],
        "outcome": "relative density",
        "direction": "increase",
        "assertion_strength": "associative",
        "attribution_scope": "isolated_effect",
        "synthesis_status": synthesis_status,
        "certainty": 0.8,
        "mechanisms": [],
        "scientific_context": {"material": [], "sample": [], "process": [], "test": []},
        "limitations": ["One directly contributing paper."],
        "paper_contributions": [
            {
                "document_id": "paper-1",
                "analysis_status": "analyzed",
                "supporting_evidence_ids": ["evidence-1"],
                "contradicting_evidence_ids": [],
                "context_evidence_ids": [],
                "condition_boundary_evidence_ids": [],
            }
        ],
    }
    evidence = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 2,
        "evidence_id": "evidence-1",
        "document_id": "paper-1",
        "source_kind": "text_window",
        "source_ref": "block-1",
        "source_excerpt": DIRECT_SOURCE_TEXT,
        "page_numbers": [4],
        "evidence_role": "direct_result",
        "changed_variables": [
            {
                "name": "volumetric energy density",
                "baseline_value": "low VED",
                "target_value": "higher VED",
                "unit": "J/mm3",
            }
        ],
        "comparison": {
            "baseline_label": "low VED",
            "target_label": "high VED",
            "axis_names": ["volumetric energy density"],
            "comparable": True,
            "incomparability_reasons": [],
        },
        "reported_result": {
            "outcome": "relative density",
            "value": 99.6,
            "unit": "%",
            "direction": "increase",
            "result_text": DIRECT_SOURCE_TEXT,
        },
        "attribution_scope": "isolated_effect",
    }
    return {
        "objective": {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "question": "How does VED affect density?",
            "confirmation_status": "confirmed",
        },
        "published_analysis": {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "analysis_version": 2,
            "status": "succeeded",
            "processed_document_count": 1,
            "total_document_count": 1,
        },
        "paper_contributions": [
            {"document_id": "paper-1", "analysis_status": "analyzed"}
        ],
        "findings": [finding],
        "evidence_by_finding": {"finding-1": [evidence]},
        "feedback_by_finding": {"finding-1": []},
        "curations_by_finding": {"finding-1": []},
        "dataset_items": [
            {
                "finding_id": "finding-1",
                "label_status": "candidate",
                "dataset_use_status": "review_candidate",
                "expert_target": None,
            }
        ],
        "training_jsonl_rows": [],
    }


def _add_second_direct_result(
    bundle: dict,
    *,
    evidence_role: str = "direct_result",
    direction: str = "increase",
) -> str:
    source_text = (
        "Relative density increased from 95.4% to 99.6% at higher VED."
        if direction == "increase"
        else "Relative density decreased from 99.6% to 95.4% at higher VED."
    )
    contribution = {
        "document_id": "paper-2",
        "analysis_status": "analyzed",
        "supporting_evidence_ids": (
            ["evidence-2"] if evidence_role == "direct_result" else []
        ),
        "contradicting_evidence_ids": (
            ["evidence-2"] if evidence_role == "contradictory_result" else []
        ),
        "context_evidence_ids": [],
        "condition_boundary_evidence_ids": [],
    }
    bundle["findings"][0]["paper_contributions"].append(contribution)
    bundle["paper_contributions"].append(
        {"document_id": "paper-2", "analysis_status": "analyzed"}
    )
    bundle["published_analysis"].update(
        {"processed_document_count": 2, "total_document_count": 2}
    )
    bundle["evidence_by_finding"]["finding-1"].append(
        {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "analysis_version": 2,
            "evidence_id": "evidence-2",
            "document_id": "paper-2",
            "source_kind": "text_window",
            "source_ref": "block-2",
            "source_excerpt": source_text,
            "page_numbers": [5],
            "evidence_role": evidence_role,
            "changed_variables": [
                {
                    "name": "volumetric energy density",
                    "baseline_value": "low VED",
                    "target_value": "higher VED",
                    "unit": "J/mm3",
                }
            ],
            "comparison": {
                "baseline_label": "low VED",
                "target_label": "high VED",
                "axis_names": ["volumetric energy density"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "relative density",
                "value": 99.6 if direction == "increase" else 95.4,
                "unit": "%",
                "direction": direction,
                "result_text": source_text,
            },
            "attribution_scope": "isolated_effect",
        }
    )
    return source_text


def test_canonical_finding_and_source_excerpt_pass() -> None:
    checker = _load_module()
    result = checker.evaluate_objective_bundle(
        _bundle(),
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    assert all(check["status"] == "pass" for check in result["checks"])
    assert result["finding_count"] == 1
    assert result["evidence_count"] == 1


def test_factor_unit_suffixes_do_not_change_axis_identity() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["findings"][0]["factors"] = [
        "volumetric energy density [J/mm3]"
    ]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    factor_check = next(
        check
        for check in result["checks"]
        if check["check"]
        == "Finding finding-1 factors cover every direct Evidence changed variable"
    )
    assert factor_check["status"] == "pass"


def test_returned_context_evidence_does_not_fail_direct_support_check() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["findings"][0]["paper_contributions"][0]["context_evidence_ids"].append(
        "context-1"
    )
    bundle["evidence_by_finding"]["finding-1"].append(
        {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "analysis_version": 2,
            "evidence_id": "context-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-2",
            "source_excerpt": "Samples were tested at room temperature.",
            "page_numbers": [3],
            "evidence_role": "condition_context",
        }
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-1", "text_window", "block-2"): {
                "text": "Samples were tested at room temperature.",
                "page": 3,
            },
        },
    )

    assert all(check["status"] == "pass" for check in result["checks"])
    assert result["evidence_count"] == 2


def test_synthesized_finding_requires_two_direct_documents() -> None:
    checker = _load_module()
    result = checker.evaluate_objective_bundle(
        _bundle(synthesis_status="agreement"),
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 synthesis matches direct paper support" in failed


def test_source_excerpt_mismatch_blocks_the_audit() -> None:
    checker = _load_module()
    failure = _failure_modes()["source_mismatch"]
    result = checker.evaluate_objective_bundle(
        _bundle(),
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": failure["incorrect_source_text"],
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "all Evidence excerpts match Source artifacts" in failed


def test_incomplete_candidate_paper_traversal_blocks_the_audit() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["published_analysis"]["processed_document_count"] = 5
    bundle["published_analysis"]["total_document_count"] = 6

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "analysis traversed every candidate paper" in failed
    assert "analysis has one terminal PaperContribution per candidate paper" in failed


def test_failed_paper_contribution_does_not_count_as_expert_traversal() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["paper_contributions"][0]["analysis_status"] = "failed"

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "analysis has one terminal PaperContribution per candidate paper" in failed
    assert result["verdict"] == "fail"


def test_jointly_varied_factors_cannot_be_audited_as_isolated_ved() -> None:
    checker = _load_module()
    failure = _failure_modes()["coupled_variables"]
    bundle = _bundle()
    finding = bundle["findings"][0]
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence["changed_variables"] = failure["changed_variables"]
    evidence["comparison"]["axis_names"] = [
        "scan speed",
        "hatch spacing",
        "volumetric energy density",
    ]
    evidence["attribution_scope"] = "joint_effect"
    finding["factors"] = failure["incorrect_finding_factors"]
    finding["attribution_scope"] = "isolated_effect"
    finding["assertion_strength"] = "causal"

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 factors cover every direct Evidence changed variable" in failed
    assert "Finding finding-1 attribution matches direct Evidence" in failed
    assert "Finding finding-1 does not overclaim coupled variables" in failed


def test_table_value_must_bind_to_the_named_experiment_group() -> None:
    checker = _load_module()
    failure = _failure_modes()["wrong_value_binding"]
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    source_text = failure["source_text"]
    evidence.update(
        {
            "source_kind": "table",
            "source_ref": "table-1",
            "source_excerpt": source_text,
            "changed_variables": [
                {
                    "name": "volumetric energy density",
                    "baseline_value": failure["incorrect_baseline_value"],
                    "target_value": failure["incorrect_target_value"],
                    "unit": "J/mm3",
                }
            ],
            "comparison": {
                "baseline_label": failure["baseline_label"],
                "target_label": failure["target_label"],
                "axis_names": ["volumetric energy density"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "elongation",
                "value": failure["target_result_value"],
                "unit": "%",
                "direction": "increase",
                "result_text": "Elongation reached 40.8% for as-SLM(140/100).",
            },
        }
    )
    bundle["findings"][0]["outcome"] = "elongation"

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "table", "table-1"): {
                "text": source_text,
                "page": 4,
                "rows": failure["rows"],
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "all table Evidence values bind to the named experiment rows" in failed


def test_table_variable_values_must_bind_to_the_named_variable_column() -> None:
    checker = _load_module()
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    source_text = "Scan speed | Relative density\n700 | 0\n800 | 45"
    evidence.update(
        {
            "source_kind": "table",
            "source_ref": "table-1",
            "source_excerpt": source_text,
            "related_source_refs": [],
            "changed_variables": [
                {
                    "name": "volumetric energy density",
                    "baseline_value": 0,
                    "target_value": 45,
                    "unit": "J/mm3",
                }
            ],
            "comparison": {
                "baseline_label": "700",
                "target_label": "800",
                "axis_names": ["volumetric energy density"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "relative density",
                "value": 45,
                "unit": "%",
                "direction": "increase",
                "result_text": "Relative density increased to 45%.",
            },
        }
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "table", "table-1"): {
                "text": source_text,
                "page": 4,
                "rows": [
                    ["Scan speed", "Relative density"],
                    ["700", "0"],
                    ["800", "45"],
                ],
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "all table Evidence values bind to the named experiment rows" in failed


def test_correct_table_group_and_value_binding_passes() -> None:
    checker = _load_module()
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    source_text = "Specimen | VED | Elongation\nas-SLM(140/100) | 389 | 40.8\nas-SLM(100/100) | 278 | 28.9"
    evidence.update(
        {
            "source_kind": "table",
            "source_ref": "table-1",
            "source_excerpt": source_text,
            "changed_variables": [
                {
                    "name": "volumetric energy density",
                    "baseline_value": 278,
                    "target_value": 389,
                    "unit": "J/mm3",
                }
            ],
            "comparison": {
                "baseline_label": "as-SLM(100/100)",
                "target_label": "as-SLM(140/100)",
                "axis_names": ["volumetric energy density"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "elongation",
                "value": 40.8,
                "unit": "%",
                "direction": "increase",
                "result_text": "Elongation reached 40.8% for as-SLM(140/100).",
            },
        }
    )
    bundle["findings"][0]["outcome"] = "elongation"
    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "table", "table-1"): {
                "text": source_text,
                "page": 4,
                "rows": [
                    ["Specimen", "VED", "Elongation"],
                    ["as-SLM(140/100)", "389", "40.8"],
                    ["as-SLM(100/100)", "278", "28.9"],
                ],
            }
        },
    )

    assert all(check["status"] == "pass" for check in result["checks"])


def test_composite_pairwise_table_evidence_audits_related_source_rows() -> None:
    checker = _load_module()
    bundle = _bundle()
    finding = bundle["findings"][0]
    finding.update(
        {
            "statement": (
                "Scan strategy and scanning speed were associated with higher "
                "yield strength."
            ),
            "factors": ["Scan strategy", "Scanning speed (mm/s)"],
            "outcome": "yield strength",
            "attribution_scope": "joint_effect",
        }
    )
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence.update(
        {
            "source_kind": "table",
            "source_ref": "result-table",
            "source_excerpt": (
                "Condition: 1 | Sample: 3 | Yield Strength (MPa): 169.4\n"
                "Condition: 1 | Sample: 3 | Scan strategy: C | "
                "Scanning speed (mm/s): 0.25\n"
                "Condition: 3 | Sample: 5 | Yield Strength (MPa): 302.24\n"
                "Condition: 3 | Sample: 5 | Scan strategy: A | "
                "Scanning speed (mm/s): 0.12"
            ),
            "page_numbers": [3],
            "related_source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "result-table",
                    "page": 3,
                    "row_index": 1,
                    "col_index": 2,
                },
                {
                    "source_kind": "table",
                    "source_ref": "process-table",
                    "page": 2,
                    "row_index": 1,
                },
                {
                    "source_kind": "table",
                    "source_ref": "result-table",
                    "page": 3,
                    "row_index": 2,
                    "col_index": 2,
                },
                {
                    "source_kind": "table",
                    "source_ref": "process-table",
                    "page": 2,
                    "row_index": 2,
                },
            ],
            "changed_variables": [
                {
                    "name": "Scan strategy",
                    "baseline_value": "C",
                    "target_value": "A",
                },
                {
                    "name": "Scanning speed (mm/s)",
                    "baseline_value": 0.25,
                    "target_value": 0.12,
                },
            ],
            "comparison": {
                "baseline_label": "3",
                "target_label": "5",
                "axis_names": ["Scan strategy", "Scanning speed (mm/s)"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "yield strength",
                "value": 302.24,
                "unit": "MPa",
                "direction": "increase",
                "result_text": (
                    "Yield strength changed from 169.4 to 302.24 MPa between "
                    "samples 3 and 5."
                ),
            },
            "attribution_scope": "joint_effect",
        }
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "table", "result-table"): {
                "text": "Condition | Sample | Yield Strength (MPa)",
                "page": 3,
                "rows": [
                    ["Condition", "Sample", "Yield Strength (MPa)"],
                    ["1", "3", "169.4"],
                    ["3", "5", "302.24"],
                ],
            },
            ("paper-1", "table", "process-table"): {
                "text": (
                    "Condition | Sample | Scan strategy | Scanning speed (mm/s)"
                ),
                "page": 2,
                "rows": [
                    [
                        "Condition",
                        "Sample",
                        "Scan strategy",
                        "Scanning speed (mm/s)",
                    ],
                    ["1", "3", "C", "0.25"],
                    ["3", "5", "A", "0.12"],
                ],
            },
        },
    )

    checks = {check["check"]: check["status"] for check in result["checks"]}
    assert checks["all Evidence records have exact source locators"] == "pass"
    assert checks["all Evidence excerpts match Source artifacts"] == "pass"
    assert checks["all Evidence pages match Source artifacts"] == "pass"
    assert checks["all table Evidence values bind to the named experiment rows"] == "pass"


def test_composite_pairwise_excerpt_rejects_an_unreferenced_source_row() -> None:
    checker = _load_module()
    evidence = {
        "document_id": "paper-1",
        "source_kind": "table",
        "source_ref": "result-table",
        "source_excerpt": (
            "Sample: A | Yield strength: 300\n"
            "Sample: B | Yield strength: 340\n"
            "Sample: C | Yield strength: 360"
        ),
        "page_numbers": [3],
        "evidence_role": "direct_result",
        "related_source_refs": [
            {
                "source_kind": "table",
                "source_ref": "result-table",
                "page": 3,
                "row_index": 1,
            },
            {
                "source_kind": "table",
                "source_ref": "result-table",
                "page": 3,
                "row_index": 2,
            },
            {
                "source_kind": "table",
                "source_ref": "process-table",
                "page": 2,
                "row_index": 1,
            },
            {
                "source_kind": "table",
                "source_ref": "process-table",
                "page": 2,
                "row_index": 2,
            },
        ],
    }
    sources = {
        ("paper-1", "table", "result-table"): {
            "text": "Sample | Yield strength",
            "page": 3,
            "rows": [
                ["Sample", "Yield strength"],
                ["A", "300"],
                ["B", "340"],
                ["C", "360"],
            ],
        },
        ("paper-1", "table", "process-table"): {
            "text": "Sample | Scan speed",
            "page": 2,
            "rows": [
                ["Sample", "Scan speed"],
                ["A", "700"],
                ["B", "800"],
            ],
        },
    }

    audit = checker._audit_source_record(evidence, sources)

    assert audit["locator_matches"] is True
    assert audit["excerpt_matches"] is False


def test_table_row_delta_rejects_undeclared_orientation_axes() -> None:
    checker = _load_module()
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    source_text = (
        "alpha | beta | theta | Yield Strength Experiment (MPa)\n"
        "0 | 0 | 0 | 334.2\n"
        "45 | 22.5 | 45 | 365.6"
    )
    evidence.update(
        {
            "source_kind": "table",
            "source_ref": "table-angle",
            "source_excerpt": source_text,
            "related_source_refs": [
                {"row_index": 1, "col_index": 3},
                {"row_index": 2, "col_index": 3},
            ],
            "changed_variables": [
                {
                    "name": "scan strategy rotation angle",
                    "baseline_value": 0,
                    "target_value": 45,
                }
            ],
            "comparison": {
                "baseline_label": "1",
                "target_label": "2",
                "axis_names": ["scan strategy rotation angle"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "yield strength experiment",
                "value": 365.6,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Yield strength increased from 334.2 to 365.6 MPa.",
            },
        }
    )
    bundle["findings"][0].update(
        {
            "statement": "Increasing scan rotation increased yield strength.",
            "factors": ["scan strategy rotation angle"],
            "outcome": "yield strength experiment",
        }
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "table", "table-angle"): {
                "text": source_text,
                "page": 4,
                "rows": [
                    [
                        "alpha",
                        "beta",
                        "theta",
                        "Yield Strength Experiment (MPa)",
                    ],
                    ["0", "0", "0", "334.2"],
                    ["45", "22.5", "45", "365.6"],
                ],
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "all table Evidence values bind to the named experiment rows" in failed


def test_context_table_does_not_require_result_group_binding() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["findings"][0]["paper_contributions"][0]["context_evidence_ids"].append(
        "context-table"
    )
    bundle["evidence_by_finding"]["finding-1"].append(
        {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "analysis_version": 2,
            "evidence_id": "context-table",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-context",
            "source_excerpt": "Specimen | Test temperature\nA | 25 C",
            "page_numbers": [3],
            "evidence_role": "condition_context",
        }
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-1", "table", "table-context"): {
                "text": "Specimen | Test temperature\nA | 25 C",
                "page": 3,
                "rows": [["Specimen", "Test temperature"], ["A", "25 C"]],
            },
        },
    )

    assert all(check["status"] == "pass" for check in result["checks"])


def test_table_row_summary_excerpt_matches_canonical_source_row() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["findings"][0]["paper_contributions"][0]["context_evidence_ids"].append(
        "context-table"
    )
    bundle["evidence_by_finding"]["finding-1"].append(
        {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "analysis_version": 2,
            "evidence_id": "context-table",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-context",
            "source_excerpt": (
                "Specimen: A | Test temperature: 25 C\n"
                "Specimen: B | Test temperature: 400 C"
            ),
            "page_numbers": [3],
            "evidence_role": "condition_context",
        }
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-1", "table", "table-context"): {
                "text": (
                    "| Specimen | Test temperature |\n"
                    "| A | 25 C |\n"
                    "| B | 400 C |"
                ),
                "page": 3,
                "rows": [
                    ["Specimen", "Test temperature"],
                    ["A", "25 C"],
                    ["B", "400 C"],
                ],
            },
        },
    )

    assert all(check["status"] == "pass" for check in result["checks"])


def test_as_slm_and_hip_slm_difference_cannot_be_attributed_to_ved() -> None:
    checker = _load_module()
    failure = _failure_modes()["sample_state_confounding"]
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence["source_excerpt"] = failure["source_excerpt"]
    evidence["changed_variables"] = failure["changed_variables"]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": failure["source_excerpt"],
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 excludes sample-state confounding" in failed


def test_paper_association_cannot_be_promoted_to_cross_paper_causality() -> None:
    checker = _load_module()
    failure = _failure_modes()["paper_association_cross_causality"]
    bundle = _bundle(
        synthesis_status=failure["incorrect_finding_synthesis_status"]
    )
    finding = bundle["findings"][0]
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence["attribution_scope"] = failure["evidence_attribution_scope"]
    finding["attribution_scope"] = failure["evidence_attribution_scope"]
    finding["assertion_strength"] = failure[
        "incorrect_finding_assertion_strength"
    ]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": "Relative density increased to 99.6% at higher VED.",
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 synthesis matches direct paper support" in failed
    assert "Finding finding-1 outcome and direction match direct Evidence" in failed


def test_latest_feedback_controls_dataset_status() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["feedback_by_finding"]["finding-1"] = [
        {
            "review_status": "correct",
            "created_at": "2026-08-02T10:00:00+00:00",
        },
        {
            "review_status": "partial",
            "created_at": "2026-08-02T11:00:00+00:00",
        },
    ]
    bundle["dataset_items"][0].update(
        {"label_status": "gold", "dataset_use_status": "training_ready"}
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 latest expert event controls dataset status" in failed


def test_direct_result_outcome_and_direction_must_match_finding() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["evidence_by_finding"]["finding-1"][0]["reported_result"].update(
        {"outcome": "porosity", "direction": "decrease"}
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 outcome and direction match direct Evidence" in failed
    assert result["verdict"] == "partial"


def test_finding_contribution_evidence_ids_must_bind_to_the_same_document() -> None:
    checker = _load_module()
    bundle = _bundle(synthesis_status="agreement")
    second_source = _add_second_direct_result(bundle)
    contributions = bundle["findings"][0]["paper_contributions"]
    contributions[0]["supporting_evidence_ids"] = ["evidence-2"]
    contributions[1]["supporting_evidence_ids"] = ["evidence-1"]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-2", "text_window", "block-2"): {
                "text": second_source,
                "page": 5,
            },
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 direct paper bindings match Evidence" in failed


def test_unreported_experiment_value_blocks_scientific_acceptance() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["evidence_by_finding"]["finding-1"][0]["reported_result"]["value"] = 98.9

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 values and experiment groups match source text" in failed


def test_as_slm_hip_comparison_requires_treatment_factor() -> None:
    checker = _load_module()
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence["comparison"].update(
        {"baseline_label": "as-SLM(100/100)", "target_label": "HIP-SLM(100/100)"}
    )
    evidence["source_excerpt"] = (
        "as-SLM(100/100) and HIP-SLM(100/100) had different relative density."
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": evidence["source_excerpt"],
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 excludes sample-state confounding" in failed


def test_real_acceptance_manifest_covers_six_papers_and_multiple_objectives() -> None:
    checker = _load_module()
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )

    manifest = checker.load_acceptance_manifest(manifest_path)

    assert manifest["schema_version"] == "objective_finding_material_acceptance.v1"
    assert len(manifest["documents"]) == 6
    assert {item["paper_id"] for item in manifest["documents"]} == {
        "P001",
        "P002",
        "P003",
        "P004",
        "P005",
        "P006",
    }
    assert all("document_id" not in item for item in manifest["documents"])
    assert all(len(item["sha256"]) == 64 for item in manifest["documents"])
    assert len(manifest["objectives"]) >= 3
    assert all("objective_id" not in item for item in manifest["objectives"])
    assert set(manifest["required_review_statuses"]) == {
        "correct",
        "partial",
        "incorrect",
    }


def test_acceptance_checker_adds_backend_root_before_manifest_resolution(
    monkeypatch,
) -> None:
    checker = _load_module()
    backend_root = str(checker.DEFAULT_BACKEND_ROOT)
    monkeypatch.setattr(
        checker.sys,
        "path",
        [entry for entry in checker.sys.path if entry != backend_root],
    )

    def assert_backend_import_path(_collection_id, _documents):
        assert backend_root in checker.sys.path
        raise RuntimeError("manifest resolution reached")

    monkeypatch.setattr(
        checker,
        "_resolve_manifest_document_ids",
        assert_backend_import_path,
    )
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )
    manifest = checker.load_acceptance_manifest(manifest_path)

    try:
        checker.check_objective_findings_projection(
            collection_id="col-1",
            objective_ids=("objective-1", "objective-2", "objective-3"),
            acceptance_manifest=manifest,
        )
    except RuntimeError as exc:
        assert str(exc) == "manifest resolution reached"
    else:
        raise AssertionError("manifest resolution should stop the acceptance check")


def test_acceptance_manifest_rejects_blank_objective_key(tmp_path: Path) -> None:
    checker = _load_module()
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["objectives"][0]["key"] = ""
    invalid_path = tmp_path / "invalid-manifest.json"
    invalid_path.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        checker.load_acceptance_manifest(invalid_path)
    except ValueError as exc:
        assert str(exc) == "acceptance manifest requires unique objectives"
    else:
        raise AssertionError("blank Objective keys must be rejected")


def test_manifest_expectations_check_exact_papers_and_scientific_terms() -> None:
    checker = _load_module()
    result = checker.evaluate_objective_bundle(
        _bundle(),
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
        expected_document_ids={"paper-1", "paper-2"},
        expected_term_groups=[["ved"], ["fatigue"]],
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "analysis covers the approved paper set" in failed
    assert "Findings cover the objective-specific material result" in failed
    assert result["verdict"] == "fail"


def test_required_review_statuses_are_checked_across_objectives() -> None:
    checker = _load_module()
    check = checker._required_review_status_check(
        required={"correct", "partial", "incorrect"},
        objectives=[
            {"review_statuses": ["correct"]},
            {"review_statuses": ["partial"]},
        ],
    )

    assert check["status"] == "fail"
    assert check["blocker"] is True
    assert "incorrect" in check["detail"]


def test_real_acceptance_requires_manifest_and_three_objectives() -> None:
    checker = _load_module()

    with pytest.raises(ValueError, match="acceptance_manifest is required"):
        checker.check_objective_findings_projection(
            collection_id="col-1",
            objective_ids=("objective-1", "objective-2", "objective-3"),
        )

    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )
    manifest = checker.load_acceptance_manifest(manifest_path)
    with pytest.raises(ValueError, match="at least three objective_ids"):
        checker.check_objective_findings_projection(
            collection_id="col-1",
            objective_ids=("objective-1",),
            acceptance_manifest=manifest,
        )


def test_real_acceptance_requires_three_distinct_manifest_objectives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _load_module()
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )
    manifest = checker.load_acceptance_manifest(manifest_path)
    same_question = "How does preheating the build platform affect microstructure?"
    monkeypatch.setattr(
        checker,
        "_resolve_manifest_document_ids",
        lambda *_args, **_kwargs: {"paper-1"},
    )
    monkeypatch.setattr(checker, "_load_source_index", lambda *_args: {})
    monkeypatch.setattr(
        checker,
        "_local_objective_bundle",
        lambda _collection_id, objective_id: {
            "objective": {"objective_id": objective_id, "question": same_question}
        },
    )
    monkeypatch.setattr(
        checker,
        "evaluate_objective_bundle",
        lambda payload, **_kwargs: {
            "verdict": "pass",
            "objective_id": payload["objective"]["objective_id"],
            "review_statuses": ["correct", "partial", "incorrect"],
            "checks": [],
        },
    )

    with pytest.raises(ValueError, match="distinct acceptance objectives"):
        checker.check_objective_findings_projection(
            collection_id="col-1",
            objective_ids=("objective-1", "objective-2", "objective-3"),
            acceptance_manifest=manifest,
        )


def test_acceptance_manifest_requires_exactly_six_papers_and_three_objectives(
    tmp_path: Path,
) -> None:
    checker = _load_module()
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["documents"] = manifest["documents"][:5]
    invalid_documents = tmp_path / "five-papers.json"
    invalid_documents.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly six papers"):
        checker.load_acceptance_manifest(invalid_documents)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["objectives"] = manifest["objectives"][:2]
    invalid_objectives = tmp_path / "two-objectives.json"
    invalid_objectives.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="at least three objectives"):
        checker.load_acceptance_manifest(invalid_objectives)


def test_agreement_requires_two_same_direction_supporting_papers() -> None:
    checker = _load_module()
    bundle = _bundle(synthesis_status="agreement")
    second_source = _add_second_direct_result(bundle)

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-2", "text_window", "block-2"): {
                "text": second_source,
                "page": 5,
            },
        },
    )

    assert all(check["status"] == "pass" for check in result["checks"])


def test_conflict_requires_opposing_direct_evidence() -> None:
    checker = _load_module()
    bundle = _bundle(synthesis_status="conflict")
    second_source = _add_second_direct_result(bundle)

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-2", "text_window", "block-2"): {
                "text": second_source,
                "page": 5,
            },
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 synthesis status matches Evidence roles" in failed


def test_condition_dependent_requires_context_boundary_evidence() -> None:
    checker = _load_module()
    bundle = _bundle(synthesis_status="condition_dependent")
    second_source = _add_second_direct_result(bundle)
    bundle["findings"][0]["paper_contributions"][1][
        "condition_boundary_evidence_ids"
    ] = ["evidence-2"]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-2", "text_window", "block-2"): {
                "text": second_source,
                "page": 5,
            },
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 synthesis status matches Evidence roles" in failed


def test_condition_dependent_requires_a_disjoint_context_between_opposing_papers(
) -> None:
    checker = _load_module()
    bundle = _bundle(synthesis_status="condition_dependent")
    second_source = _add_second_direct_result(
        bundle,
        evidence_role="contradictory_result",
        direction="decrease",
    )
    context_text = "Both samples were tested at room temperature."
    bundle["evidence_by_finding"]["finding-1"].append(
        {
            "collection_id": "col-1",
            "objective_id": "objective-1",
            "analysis_version": 2,
            "evidence_id": "context-2",
            "document_id": "paper-2",
            "source_kind": "text_window",
            "source_ref": "block-context",
            "source_excerpt": context_text,
            "page_numbers": [6],
            "evidence_role": "condition_context",
            "scientific_context": {
                "material": [],
                "sample": [],
                "process": [],
                "test": [{"name": "temperature", "value": "room"}],
            },
        }
    )
    contribution = bundle["findings"][0]["paper_contributions"][1]
    contribution["context_evidence_ids"] = ["context-2"]
    contribution["condition_boundary_evidence_ids"] = ["context-2"]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-2", "text_window", "block-2"): {
                "text": second_source,
                "page": 5,
            },
            ("paper-2", "text_window", "block-context"): {
                "text": context_text,
                "page": 6,
            },
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 synthesis status matches Evidence roles" in failed


def test_source_audit_requires_explicit_matching_pdf_page() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["evidence_by_finding"]["finding-1"][0]["page_numbers"] = []

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "all Evidence pages match Source artifacts" in failed


def test_source_audit_rejects_ambiguous_page_lists_for_source_jump() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["evidence_by_finding"]["finding-1"][0]["page_numbers"] = [999, 4]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "all Evidence pages match Source artifacts" in failed


def test_finding_and_evidence_require_complete_scoped_identity() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["findings"][0]["collection_id"] = "col-other"
    bundle["evidence_by_finding"]["finding-1"][0]["analysis_version"] = 3

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 uses the published composite identity" in failed
    assert "Finding finding-1 Evidence uses the published composite identity" in failed


def test_finding_statement_numbers_preserve_sign_and_bind_to_one_evidence() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["findings"][0]["statement"] = (
        "Higher VED changed relative density by -99.6%."
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 statement values bind to one supporting Evidence" in failed
    assert checker._numbers("1.90x10^5 cycles") == (checker.Decimal("190000"),)
    assert checker._numbers("1.90×10^5 cycles") == (checker.Decimal("190000"),)
    assert checker._numbers("0,5 mm") == (checker.Decimal("0.5"),)
    assert checker._numbers("1,90×10^5 cycles") == (checker.Decimal("190000"),)


def test_finding_statement_cannot_use_a_number_only_present_in_result_text() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["findings"][0]["statement"] = (
        "Higher VED increased relative density to 123.4%."
    )
    bundle["evidence_by_finding"]["finding-1"][0]["reported_result"][
        "result_text"
    ] = "Relative density increased to 123.4%."

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 statement values bind to one supporting Evidence" in failed


def test_training_jsonl_excludes_latest_partial_feedback() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["feedback_by_finding"]["finding-1"] = [
        {"review_status": "correct", "created_at": "2026-08-02T10:00:00+00:00"},
        {"review_status": "partial", "created_at": "2026-08-02T11:00:00+00:00"},
    ]
    bundle["dataset_items"][0].update(
        {"label_status": "silver", "dataset_use_status": "review_candidate"}
    )
    bundle["training_jsonl_rows"] = [
        {
            "messages": [
                {"role": "user", "content": "Evidence"},
                {"role": "assistant", "content": "Finding"},
            ],
            "metadata": {
                "collection_id": "col-1",
                "objective_id": "objective-1",
                "analysis_version": 2,
                "finding_id": "finding-1",
            },
        }
    ]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "training_jsonl contains exactly the latest training-ready Findings" in failed


def test_training_jsonl_matches_latest_training_ready_dataset_item() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["feedback_by_finding"]["finding-1"] = [
        {"review_status": "correct", "created_at": "2026-08-02T10:00:00+00:00"}
    ]
    training_target = {"finding_id": "finding-1"}
    messages = [
        {"role": "user", "content": f"Evidence: {DIRECT_SOURCE_TEXT}"},
        {"role": "assistant", "content": json.dumps(training_target)},
    ]
    metadata = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 2,
        "finding_id": "finding-1",
    }
    bundle["dataset_items"][0].update(
        {
            "label_status": "gold",
            "dataset_use_status": "training_ready",
            "training_messages": messages,
            "training_target": training_target,
            "metadata": metadata,
        }
    )
    bundle["training_jsonl_rows"] = [
        {"messages": messages, "metadata": metadata}
    ]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    assert all(check["status"] == "pass" for check in result["checks"])


def test_training_jsonl_validates_roles_evidence_and_training_target() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["feedback_by_finding"]["finding-1"] = [
        {"review_status": "correct", "created_at": "2026-08-02T10:00:00+00:00"}
    ]
    training_target = {"statement": "Grounded target."}
    messages = [
        {"role": "assistant", "content": "Evidence omitted"},
        {"role": "user", "content": json.dumps({"statement": "Wrong target."})},
    ]
    metadata = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 2,
        "finding_id": "finding-1",
    }
    bundle["dataset_items"][0].update(
        {
            "label_status": "gold",
            "dataset_use_status": "training_ready",
            "training_messages": messages,
            "training_target": training_target,
            "metadata": metadata,
        }
    )
    bundle["training_jsonl_rows"] = [{"messages": messages, "metadata": metadata}]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "training_jsonl contains exactly the latest training-ready Findings" in failed
