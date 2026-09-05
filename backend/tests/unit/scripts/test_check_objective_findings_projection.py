from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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


@pytest.mark.anyio
async def test_local_bundle_preserves_complete_evidence_across_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _load_module()

    class Record:
        def __init__(self, **payload):
            self.__dict__.update(payload)

        def to_record(self):
            return dict(self.__dict__)

    findings = [Record(finding_id="finding-1"), Record(finding_id="finding-2")]
    published_evidence = [
        Record(evidence_id="evidence-1"),
        Record(evidence_id="evidence-2"),
        Record(evidence_id="context-1"),
    ]

    class ObjectiveRepository:
        async def read_objective(self, _collection_id, _objective_id):
            return Record(
                collection_id="col-1",
                objective_id="objective-1",
                published_analysis_version=2,
            )

        async def read_analysis(self, *_args):
            return Record(analysis_version=2)

        async def list_contributions(self, *_args):
            return []

        async def list_findings(self, *_args, **_kwargs):
            return findings, len(findings)

        async def list_evidence(self, *_args, finding_id=None, **_kwargs):
            if finding_id == "finding-1":
                return [published_evidence[0]], 1
            if finding_id == "finding-2":
                return [published_evidence[1]], 1
            return published_evidence, len(published_evidence)

    class ReviewRepository:
        async def list_feedback(self, *_args):
            return []

        async def list_curations(self, *_args):
            return []

    database = __import__("infra.persistence.database", fromlist=["database"])
    objective_repository = __import__(
        "infra.persistence.postgres.objective_repository",
        fromlist=["objective_repository"],
    )
    review_repository = __import__(
        "infra.persistence.postgres.finding_review_repository",
        fromlist=["finding_review_repository"],
    )
    evaluation = __import__("application.evaluation", fromlist=["evaluation"])
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(database, "build_database_engine", lambda _settings: engine)
    monkeypatch.setattr(database, "build_session_factory", lambda _engine: None)
    monkeypatch.setattr(
        objective_repository,
        "PostgresObjectiveRepository",
        lambda _sessions: ObjectiveRepository(),
    )
    monkeypatch.setattr(
        review_repository,
        "PostgresFindingReviewRepository",
        lambda _sessions: ReviewRepository(),
    )
    monkeypatch.setattr(
        evaluation,
        "FindingFeedbackService",
        lambda **_kwargs: SimpleNamespace(
            export_dataset=AsyncMock(return_value={"items": []})
        ),
    )

    bundle = await checker._local_objective_bundle("col-1", "objective-1")

    assert [item["evidence_id"] for item in bundle["evidence"]] == [
        "evidence-1",
        "evidence-2",
        "context-1",
    ]
    assert set(bundle["evidence_by_finding"]) == {"finding-1", "finding-2"}
    engine.dispose.assert_awaited_once()


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


def test_scalar_table_result_binds_to_its_exact_row_and_result_column() -> None:
    checker = _load_module()
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence.update(
        {
            "source_kind": "table",
            "source_ref": "table-1",
            "source_excerpt": (
                "Condition number: 5 | Sample number: 11 | Energy density "
                "(J/mm3): 100 | Relative density: 96.2"
            ),
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "relative density",
                "value": 96.2,
                "unit": None,
                "direction": "unknown",
                "result_text": "relative density = 96.2",
            },
            "related_source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "page": 2,
                    "row_index": 1,
                    "col_index": 3,
                    "header_path": "Relative density",
                },
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-1",
                    "page": 3,
                },
            ],
            "page_numbers": [2],
        }
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "table", "table-1"): {
                "text": (
                    "Condition number | Sample number | Energy density (J/mm3) "
                    "| Relative density\n5 | 11 | 100 | 96.2"
                ),
                "page": 2,
                "rows": [
                    [
                        "Condition number",
                        "Sample number",
                        "Energy density (J/mm3)",
                        "Relative density",
                    ],
                    ["5", "11", "100", "96.2"],
                ],
            },
            ("paper-1", "text_window", "methods-1"): {
                "text": "The specimens were produced by laser powder bed fusion.",
                "page": 3,
            },
        },
    )

    table_check = next(
        check
        for check in result["checks"]
        if check["check"]
        == "all table Evidence values bind to the named experiment rows"
    )
    assert table_check["status"] == "pass"


def test_pairwise_table_evidence_audits_related_rows_without_excerpt_concatenation(
) -> None:
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
                "Condition: 3 | Sample: 5 | Yield Strength (MPa): 302.24"
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


def test_table_audit_keeps_related_context_out_of_the_primary_excerpt() -> None:
    checker = _load_module()
    evidence = {
        "document_id": "paper-1",
        "source_kind": "table",
        "source_ref": "result-table",
        "source_excerpt": (
            "Sample: A | Yield strength: 300\n"
            "Sample: B | Yield strength: 340"
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
    assert audit["excerpt_matches"] is True


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


def test_table_excerpt_accepts_only_a_source_bound_verified_repair() -> None:
    checker = _load_module()
    raw_rows = [
        ["Specimens", "Hardness (HV)"],
        ["HIP-SLM (100/", "147.6"],
        ["280)", "(+/- 9.2)"],
    ]
    repaired_rows = [
        ["Specimens", "Hardness (HV)"],
        ["HIP-SLM (100/280)", "147.6 (+/- 9.2)"],
    ]
    excerpt = "Specimens: HIP-SLM (100/280) | Hardness (HV): 147.6 (+/- 9.2)"
    visual_text = "Specimens Hardness (HV)\nHIP-SLM (100/280) 147.6 (+/- 9.2)"
    attestation = {
        "schema_version": "objective_table_repair_attestation.v1",
        "raw_matrix_sha256": sha256(
            json.dumps(
                raw_rows,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "visual_text_sha256": sha256(visual_text.encode("utf-8")).hexdigest(),
        "repaired_matrix_sha256": sha256(
            json.dumps(
                repaired_rows,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "repaired_row_index": 1,
        "repaired_row_sha256": sha256(
            json.dumps(
                repaired_rows[1],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "source_excerpt_sha256": sha256(
            " ".join(excerpt.split()).casefold().encode("utf-8")
        ).hexdigest(),
    }
    evidence = {
        "evidence_id": "evidence-repaired-row",
        "document_id": "paper-1",
        "source_kind": "table",
        "source_ref": "result-table",
        "source_excerpt": excerpt,
        "page_numbers": [3],
        "evidence_role": "condition_context",
        "related_source_refs": [
            {
                "source_kind": "table",
                "source_ref": "result-table",
                "page": 3,
                "row_index": 1,
                "table_matrix_repair_attestation": attestation,
            }
        ],
    }
    source = {
        "text": "Specimens | Hardness (HV)\nHIP-SLM (100/ | 147.6\n280) | (+/- 9.2)",
        "page": 3,
        "column_headers": raw_rows[0],
        "header_row_count": 1,
        "rows": raw_rows,
        "visual_text": visual_text,
    }

    audit = checker._audit_source_record(
        evidence,
        {("paper-1", "table", "result-table"): source},
    )

    assert audit["excerpt_matches"] is True
    stale_source = {**source, "rows": [*raw_rows[:-1], ["280)", "(+/- 9.3)"]]}
    stale_audit = checker._audit_source_record(
        evidence,
        {("paper-1", "table", "result-table"): stale_source},
    )
    assert stale_audit["excerpt_matches"] is False
    tampered_evidence = {
        **evidence,
        "source_excerpt": excerpt.replace("147.6", "148.6"),
    }
    tampered_audit = checker._audit_source_record(
        tampered_evidence,
        {("paper-1", "table", "result-table"): source},
    )
    assert tampered_audit["excerpt_matches"] is False


def test_table_candidate_without_reported_result_does_not_require_row_binding() -> None:
    checker = _load_module()
    evidence = {
        "evidence_id": "candidate-table",
        "document_id": "paper-1",
        "source_kind": "table",
        "source_ref": "result-table",
        "source_excerpt": "| Condition | El% |\n| --- | --- |\n| A | 72 |",
        "page_numbers": [3],
        "evidence_role": "direct_result",
        "selection_status": "candidate",
        "reported_result": None,
        "related_source_refs": [
            {
                "source_kind": "table",
                "source_ref": "result-table",
                "page": 3,
            }
        ],
    }
    source = {
        "text": evidence["source_excerpt"],
        "page": 3,
        "rows": [["Condition", "El%"], ["A", "72"]],
    }

    audit = checker._audit_source_record(
        evidence,
        {("paper-1", "table", "result-table"): source},
    )

    assert audit["table_binding_matches"] is True


def test_table_scalar_result_binding_uses_production_property_aliases() -> None:
    checker = _load_module()
    evidence = {
        "evidence_id": "elongation-row",
        "document_id": "paper-1",
        "source_kind": "table",
        "source_ref": "result-table",
        "source_excerpt": "Condition: A | El%: 72",
        "page_numbers": [3],
        "evidence_role": "direct_result",
        "reported_result": {
            "outcome": "elongation",
            "value": 72,
            "unit": "%",
        },
        "changed_variables": [],
        "related_source_refs": [
            {
                "source_kind": "table",
                "source_ref": "result-table",
                "page": 3,
                "row_index": 1,
                "col_index": 1,
            }
        ],
    }
    source = {
        "text": "| Condition | El% |\n| --- | --- |\n| A | 72 |",
        "page": 3,
        "rows": [["Condition", "El%"], ["A", "72"]],
    }

    audit = checker._audit_source_record(
        evidence,
        {("paper-1", "table", "result-table"): source},
    )

    assert audit["table_binding_matches"] is True


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


def test_table_audit_uses_flattened_headers_and_declared_data_row_indexes() -> None:
    checker = _load_module()
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence.update(
        {
            "source_kind": "table",
            "source_ref": "table-density",
            "source_excerpt": (
                "Sample: A | Process > Volumetric energy density (J/mm3): 70 | "
                "Result > Relative density (%): 95.4\n"
                "Sample: B | Process > Volumetric energy density (J/mm3): 100 | "
                "Result > Relative density (%): 99.6"
            ),
            "related_source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-density",
                    "page": 4,
                    "row_index": 1,
                    "col_index": 2,
                },
                {
                    "source_kind": "table",
                    "source_ref": "table-density",
                    "page": 4,
                    "row_index": 2,
                    "col_index": 2,
                },
            ],
            "changed_variables": [
                {
                    "name": "volumetric energy density",
                    "baseline_value": 70,
                    "target_value": 100,
                    "unit": "J/mm3",
                }
            ],
            "comparison": {
                "baseline_label": "A",
                "target_label": "B",
                "axis_names": ["volumetric energy density"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "relative density",
                "value": 99.6,
                "unit": "%",
                "direction": "increase",
                "result_text": "Relative density increased from 95.4% to 99.6%.",
            },
        }
    )

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "table", "table-density"): {
                "text": (
                    "| Sample | Process > Volumetric energy density (J/mm3) | "
                    "Result > Relative density (%) |\n"
                    "| --- | --- | --- |\n"
                    "| A | 70 | 95.4 |\n"
                    "| B | 100 | 99.6 |"
                ),
                "page": 4,
                "column_headers": [
                    "Sample",
                    "Process > Volumetric energy density (J/mm3)",
                    "Result > Relative density (%)",
                ],
                "header_row_count": 2,
                "rows": [
                    ["Sample", "Process", "Result"],
                    ["Sample", "Volumetric energy density (J/mm3)", "Relative density (%)"],
                    ["A", "70", "95.4"],
                    ["B", "100", "99.6"],
                ],
            }
        },
    )

    excerpt_check = next(
        check
        for check in result["checks"]
        if check["check"] == "all Evidence excerpts match Source artifacts"
    )
    binding_check = next(
        check
        for check in result["checks"]
        if check["check"]
        == "all table Evidence values bind to the named experiment rows"
    )
    assert excerpt_check["status"] == "pass"
    assert binding_check["status"] == "pass"


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


def test_unattributable_result_is_valid_only_as_insufficient_descriptive_finding() -> None:
    checker = _load_module()
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence["attribution_scope"] = "not_attributable"
    evidence["comparison"]["comparable"] = False
    evidence["comparison"]["incomparability_reasons"] = [
        "comparison groups do not bind to source process conditions"
    ]
    finding = bundle["findings"][0]
    finding["assertion_strength"] = "descriptive"
    finding["attribution_scope"] = "descriptive_only"

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


@pytest.mark.parametrize(
    ("assertion_strength", "attribution_scope", "synthesis_status"),
    [
        ("associative", "association_only", "insufficient_confirmation"),
        ("causal", "isolated_effect", "insufficient_confirmation"),
        ("descriptive", "descriptive_only", "agreement"),
    ],
)
def test_unattributable_result_cannot_be_promoted_beyond_descriptive_scope(
    assertion_strength: str,
    attribution_scope: str,
    synthesis_status: str,
) -> None:
    checker = _load_module()
    bundle = _bundle(synthesis_status=synthesis_status)
    bundle["evidence_by_finding"]["finding-1"][0][
        "attribution_scope"
    ] = "not_attributable"
    finding = bundle["findings"][0]
    finding["assertion_strength"] = assertion_strength
    finding["attribution_scope"] = attribution_scope

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
    preheating = next(
        item
        for item in manifest["objectives"]
        if item["key"] == "preheating_microstructure"
    )
    assert {
        item["label"] for item in preheating["required_source_evidence"]
    } == {
        "P002 preheating condition definition",
        "P002 fixed process context",
        "P002 observed cellular microstructure",
        "P002 cooling-rate and equiaxed-cellular conclusion",
    }
    assert {
        item["label"]: item for item in preheating["forbidden_direct_sources"]
    } == {
        "P002 cited background experiments": {
            "label": "P002 cited background experiments",
            "paper_id": "P002",
            "source_kind": "text_window",
            "source_term_groups": [
                ["Yang et al."],
                ["Al-Mg (-Sc)-Zr"],
                ["Liu et al."],
                ["TiAl alloy"],
            ],
        },
        "P003 cited prior investigation": {
            "label": "P003 cited prior investigation",
            "paper_id": "P003",
            "source_kind": "text_window",
            "source_term_groups": [["our prior investigation"]],
        },
    }
    assert preheating["required_finding_claims"] == [
        {
            "label": "P002 preheating cellular-structure observation",
            "paper_id": "P002",
            "statement_term_groups": [
                ["without preheating", "no preheating", "non-preheated"],
                [
                    "preheating the build platform to 150",
                    "preheating to 150",
                    "preheated to 150",
                ],
                ["cellular structure", "cellular microstructure"],
            ],
            "allowed_assertion_strengths": ["descriptive", "associative"],
            "allowed_attribution_scopes": [
                "descriptive_only",
                "association_only",
                "isolated_effect",
            ],
            "allowed_synthesis_statuses": ["insufficient_confirmation"],
        }
    ]


def test_acceptance_manifest_matches_specific_mechanical_outcome_question() -> None:
    checker = _load_module()
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )
    manifest = checker.load_acceptance_manifest(manifest_path)

    matched = checker._manifest_objective_for_question(
        "How does porosity affect elongation?",
        manifest["objectives"],
    )

    assert matched["key"] == "porosity_mechanical_properties"


@pytest.mark.anyio
async def test_acceptance_checker_adds_backend_root_before_manifest_resolution(
    monkeypatch,
) -> None:
    checker = _load_module()
    backend_root = str(checker.DEFAULT_BACKEND_ROOT)
    monkeypatch.setattr(
        checker.sys,
        "path",
        [entry for entry in checker.sys.path if entry != backend_root],
    )

    async def assert_backend_import_path(_collection_id, _documents):
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
        await checker.check_objective_findings_projection(
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


def test_researcher_parity_requires_decision_source_in_evidence_lineage() -> None:
    checker = _load_module()
    bundle = _bundle()
    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-1", "text_window", "methods-1"): {
                "text": (
                    "Specimens NP and P150 were fabricated without preheating "
                    "and with build-platform preheating to 150 C, respectively."
                ),
                "page": 3,
            },
        },
        expected_source_requirements=[
            {
                "label": "P002 preheating condition definition",
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_term_groups": [
                    ["NP"],
                    ["P150"],
                    ["without preheating"],
                    ["150 C"],
                ],
                "allowed_evidence_roles": ["condition_context", "direct_result"],
            }
        ],
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Evidence lineage includes P002 preheating condition definition" in failed


def test_researcher_parity_accepts_decision_source_as_related_lineage() -> None:
    checker = _load_module()
    bundle = _bundle()
    methods_text = (
        "Specimens NP and P150 were fabricated without preheating and with "
        "build-platform preheating to 150 C, respectively."
    )
    bundle["evidence_by_finding"]["finding-1"][0]["related_source_refs"] = [
        {
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "page": 3,
            "supports": ["changed_variables", "comparison.axis_names"],
        }
    ]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-1", "text_window", "methods-1"): {
                "text": methods_text,
                "page": 3,
            },
        },
        expected_source_requirements=[
            {
                "label": "P002 preheating condition definition",
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_term_groups": [
                    ["NP"],
                    ["P150"],
                    ["without preheating"],
                    ["150 C"],
                ],
                "allowed_evidence_roles": ["direct_result"],
            }
        ],
    )

    check = next(
        item
        for item in result["checks"]
        if item["check"]
        == "Evidence lineage includes P002 preheating condition definition"
    )
    assert check["status"] == "pass"


def test_researcher_parity_reads_required_context_from_complete_evidence_map() -> None:
    checker = _load_module()
    bundle = _bundle()
    methods_text = (
        "The fixed process used 200 W laser power and 1833 mm/s scan speed."
    )
    context = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 2,
        "evidence_id": "context-1",
        "document_id": "paper-1",
        "source_kind": "text_window",
        "source_ref": "methods-1",
        "source_excerpt": methods_text,
        "page_numbers": [3],
        "evidence_role": "condition_context",
        "scientific_context": {
            "material": [],
            "sample": [],
            "process": [{"name": "laser power", "value": 200, "unit": "W"}],
            "test": [],
        },
        "attribution_scope": "not_attributable",
    }
    bundle["evidence"] = [
        bundle["evidence_by_finding"]["finding-1"][0],
        context,
    ]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-1", "text_window", "methods-1"): {
                "text": methods_text,
                "page": 3,
            },
        },
        expected_source_requirements=[
            {
                "label": "fixed process controls",
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_term_groups": [["200 W"], ["1833 mm/s"]],
                "allowed_evidence_roles": ["condition_context"],
            }
        ],
    )

    check = next(
        item
        for item in result["checks"]
        if item["check"] == "Evidence lineage includes fixed process controls"
    )
    assert check["status"] == "pass"
    assert result["evidence_count"] == 2


def test_researcher_parity_rejects_prior_study_as_current_direct_evidence() -> None:
    checker = _load_module()
    bundle = _bundle()
    prior_text = (
        "In our prior investigation [24], defects affected tensile strength "
        "and elongation."
    )
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence.update(
        {
            "document_id": "paper-3",
            "source_ref": "prior-1",
            "source_excerpt": prior_text,
            "page_numbers": [7],
        }
    )
    bundle["paper_contributions"][0]["document_id"] = "paper-3"
    bundle["findings"][0]["paper_contributions"][0]["document_id"] = "paper-3"

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-3", "text_window", "prior-1"): {
                "text": prior_text,
                "page": 7,
            }
        },
        forbidden_direct_source_requirements=[
            {
                "label": "P003 cited prior investigation",
                "document_id": "paper-3",
                "source_kind": "text_window",
                "source_term_groups": [["our prior investigation"]],
            }
        ],
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Direct Evidence excludes P003 cited prior investigation" in failed


def test_researcher_parity_rejects_duplicate_source_grounded_facts() -> None:
    checker = _load_module()
    bundle = _bundle()
    duplicate = json.loads(
        json.dumps(bundle["evidence_by_finding"]["finding-1"][0])
    )
    duplicate["evidence_id"] = "evidence-duplicate"
    bundle["evidence_by_finding"]["finding-1"].append(duplicate)
    bundle["findings"][0]["paper_contributions"][0][
        "supporting_evidence_ids"
    ].append("evidence-duplicate")

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
    assert "Evidence contains no duplicate source-grounded facts" in failed


def test_researcher_parity_requires_a_bounded_decision_ready_finding() -> None:
    checker = _load_module()
    bundle = _bundle()
    requirement = {
        "label": "P002 P150 cellular-structure observation",
        "document_id": "paper-1",
        "statement_term_groups": [["P150"], ["cellular structure"]],
        "allowed_assertion_strengths": ["descriptive", "associative"],
        "allowed_attribution_scopes": ["descriptive_only", "association_only"],
        "allowed_synthesis_statuses": ["insufficient_confirmation"],
    }

    missing = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
        expected_finding_requirements=[requirement],
    )
    check_name = "Finding includes P002 P150 cellular-structure observation"
    assert next(
        check for check in missing["checks"] if check["check"] == check_name
    )["status"] == "fail"

    finding = bundle["findings"][0]
    finding["statement"] = (
        "For build platform preheating, the Source reported this microstructure "
        "observation: cellular structure is seen in the P150 condition."
    )
    finding["assertion_strength"] = "descriptive"
    finding["attribution_scope"] = "descriptive_only"
    bounded = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
        expected_finding_requirements=[requirement],
    )
    assert next(
        check for check in bounded["checks"] if check["check"] == check_name
    )["status"] == "pass"

    finding["assertion_strength"] = "causal"
    finding["attribution_scope"] = "isolated_effect"
    overclaimed = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
        expected_finding_requirements=[requirement],
    )
    assert next(
        check for check in overclaimed["checks"] if check["check"] == check_name
    )["status"] == "fail"


def test_real_acceptance_allows_scientifically_equivalent_preheating_wording() -> None:
    checker = _load_module()
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )
    manifest = checker.load_acceptance_manifest(manifest_path)
    requirement = dict(
        next(
            item
            for item in manifest["objectives"]
            if item["key"] == "preheating_microstructure"
        )["required_finding_claims"][0]
    )
    requirement["document_id"] = "paper-1"
    bundle = _bundle()
    finding = bundle["findings"][0]
    finding["statement"] = (
        "For build platform preheating (baseline: without preheating the build "
        "platform; target: with preheating the build platform to 150 C), the "
        "Source reported a cellular structure."
    )
    finding["assertion_strength"] = "associative"
    finding["attribution_scope"] = "isolated_effect"
    finding["synthesis_status"] = "insufficient_confirmation"

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            }
        },
        expected_finding_requirements=[requirement],
    )

    check_name = "Finding includes P002 preheating cellular-structure observation"
    assert next(
        check for check in result["checks"] if check["check"] == check_name
    )["status"] == "pass"


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


@pytest.mark.anyio
async def test_real_acceptance_requires_manifest_and_three_objectives() -> None:
    checker = _load_module()

    with pytest.raises(ValueError, match="acceptance_manifest is required"):
        await checker.check_objective_findings_projection(
            collection_id="col-1",
            objective_ids=("objective-1", "objective-2", "objective-3"),
        )

    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )
    manifest = checker.load_acceptance_manifest(manifest_path)
    with pytest.raises(ValueError, match="at least three objective_ids"):
        await checker.check_objective_findings_projection(
            collection_id="col-1",
            objective_ids=("objective-1",),
            acceptance_manifest=manifest,
        )


@pytest.mark.anyio
async def test_real_acceptance_requires_three_distinct_manifest_objectives(
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
        AsyncMock(
            return_value={
                f"P{index:03d}": f"paper-{index}" for index in range(1, 7)
            }
        ),
    )
    monkeypatch.setattr(checker, "_load_source_index", AsyncMock(return_value={}))
    monkeypatch.setattr(
        checker,
        "_local_objective_bundle",
        AsyncMock(side_effect=lambda _collection_id, objective_id: {
            "objective": {"objective_id": objective_id, "question": same_question}
        }),
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
        await checker.check_objective_findings_projection(
            collection_id="col-1",
            objective_ids=("objective-1", "objective-2", "objective-3"),
            acceptance_manifest=manifest,
        )


@pytest.mark.anyio
async def test_acceptance_resolves_paper_source_requirements_to_collection_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _load_module()
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures/expert_gold/objective_finding_acceptance.json"
    )
    manifest = checker.load_acceptance_manifest(manifest_path)
    document_ids = {
        f"P{index:03d}": f"paper-{index}" for index in range(1, 7)
    }
    monkeypatch.setattr(
        checker,
        "_resolve_manifest_document_ids",
        AsyncMock(return_value=document_ids),
    )
    monkeypatch.setattr(checker, "_load_source_index", AsyncMock(return_value={}))
    questions = {
        "objective-1": "How does build platform preheating affect microstructure?",
        "objective-2": "How does heat treatment affect microstructure?",
        "objective-3": "How does scan strategy rotation angle affect yield strength?",
    }
    monkeypatch.setattr(
        checker,
        "_local_objective_bundle",
        AsyncMock(
            side_effect=lambda _collection_id, objective_id: {
                "objective": {
                    "objective_id": objective_id,
                    "question": questions[objective_id],
                }
            }
        ),
    )
    calls: list[dict] = []

    def capture_evaluation(payload, **kwargs):  # noqa: ANN001
        calls.append(kwargs)
        return {
            "verdict": "pass",
            "objective_id": payload["objective"]["objective_id"],
            "review_statuses": ["correct", "partial", "incorrect"],
            "checks": [],
        }

    monkeypatch.setattr(checker, "evaluate_objective_bundle", capture_evaluation)

    await checker.check_objective_findings_projection(
        collection_id="col-1",
        objective_ids=("objective-1", "objective-2", "objective-3"),
        acceptance_manifest=manifest,
    )

    assert calls[0]["expected_document_ids"] == set(document_ids.values())
    assert {
        item["document_id"]
        for item in calls[0]["expected_source_requirements"]
    } == {"paper-2"}
    assert {
        item["document_id"]
        for item in calls[0]["forbidden_direct_source_requirements"]
    } == {"paper-2", "paper-3"}


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
    assert checker._numbers("that is 98.25.") == (checker.Decimal("98.25"),)


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


def test_experiment_endpoint_may_be_grounded_in_exact_related_source() -> None:
    checker = _load_module()
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence["changed_variables"] = [
        {
            "name": "build platform preheating",
            "baseline_value": "NP",
            "target_value": 150,
            "unit": "C",
        }
    ]
    evidence["related_source_refs"] = [
        {
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "page": 3,
            "supports": ["changed_variables"],
        }
    ]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-1", "text_window", "methods-1"): {
                "text": (
                    "Specimens NP and P150 were fabricated without preheating "
                    "and with build-platform preheating to 150 C, respectively."
                ),
                "page": 3,
            },
        },
    )

    check = next(
        item
        for item in result["checks"]
        if item["check"]
        == "Finding finding-1 values and experiment groups match source text"
    )
    assert check["status"] == "pass"


def test_experiment_endpoint_absent_from_complete_lineage_still_fails() -> None:
    checker = _load_module()
    bundle = _bundle()
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence["changed_variables"] = [
        {
            "name": "build platform preheating",
            "baseline_value": "NP",
            "target_value": 400,
            "unit": "C",
        }
    ]
    evidence["related_source_refs"] = [
        {
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "page": 3,
            "supports": ["changed_variables"],
        }
    ]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-1", "text_window", "methods-1"): {
                "text": (
                    "Specimens NP and P150 were fabricated without preheating "
                    "and with build-platform preheating to 150 C, respectively."
                ),
                "page": 3,
            },
        },
    )

    check = next(
        item
        for item in result["checks"]
        if item["check"]
        == "Finding finding-1 values and experiment groups match source text"
    )
    assert check["status"] == "fail"


def test_finding_number_may_be_grounded_in_exact_related_source() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["findings"][0]["statement"] = (
        "Preheating to 150 C was associated with higher relative density."
    )
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence["related_source_refs"] = [
        {
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "page": 3,
            "supports": ["changed_variables"],
        }
    ]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-1", "text_window", "methods-1"): {
                "text": "P150 used build-platform preheating to 150 C.",
                "page": 3,
            },
        },
    )

    check = next(
        item
        for item in result["checks"]
        if item["check"]
        == "Finding finding-1 statement values bind to one supporting Evidence"
    )
    assert check["status"] == "pass"


def test_finding_number_absent_from_complete_lineage_still_fails() -> None:
    checker = _load_module()
    bundle = _bundle()
    bundle["findings"][0]["statement"] = (
        "Preheating to 400 C was associated with higher relative density."
    )
    evidence = bundle["evidence_by_finding"]["finding-1"][0]
    evidence["related_source_refs"] = [
        {
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "page": 3,
            "supports": ["changed_variables"],
        }
    ]

    result = checker.evaluate_objective_bundle(
        bundle,
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": DIRECT_SOURCE_TEXT,
                "page": 4,
            },
            ("paper-1", "text_window", "methods-1"): {
                "text": "P150 used build-platform preheating to 150 C.",
                "page": 3,
            },
        },
    )

    check = next(
        item
        for item in result["checks"]
        if item["check"]
        == "Finding finding-1 statement values bind to one supporting Evidence"
    )
    assert check["status"] == "fail"


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
