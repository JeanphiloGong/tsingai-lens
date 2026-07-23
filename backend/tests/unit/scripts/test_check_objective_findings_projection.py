from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts/evaluation/expert_gold/check_objective_findings_projection.py"
    )
    spec = importlib.util.spec_from_file_location("check_objective_findings_projection", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _bundle(*, level: str = "paper", paper_count: int = 1):
    finding = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 2,
        "finding_id": "finding-1",
        "finding_level": level,
        "statement": "Higher VED was associated with higher relative density.",
        "variables": ["volumetric energy density"],
        "outcomes": ["relative density"],
        "paper_count": paper_count,
        "derivation": {
            "supporting_evidence_ids": ["evidence-1"],
            "contributing_document_ids": ["paper-1"],
        },
    }
    evidence = {
        "collection_id": "col-1",
        "objective_id": "objective-1",
        "analysis_version": 2,
        "evidence_id": "evidence-1",
        "document_id": "paper-1",
        "source_kind": "text_window",
        "source_ref": "block-1",
        "source_excerpt": "Relative density increased to 99.6% at higher VED.",
        "page_numbers": [4],
        "evidence_role": "direct_result",
    }
    return {
        "objective": {
            "objective_id": "objective-1",
            "question": "How does VED affect density?",
            "confirmation_status": "confirmed",
        },
        "published_analysis": {"analysis_version": 2, "status": "succeeded"},
        "findings": [finding],
        "evidence_by_finding": {"finding-1": [evidence]},
    }


def test_canonical_finding_and_source_excerpt_pass() -> None:
    checker = _load_module()
    result = checker.evaluate_objective_bundle(
        _bundle(),
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": "Relative density increased to 99.6% at higher VED.",
                "page": 4,
            }
        },
    )

    assert all(check["status"] == "pass" for check in result["checks"])
    assert result["finding_count"] == 1
    assert result["evidence_count"] == 1


def test_returned_context_evidence_does_not_fail_direct_support_check() -> None:
    checker = _load_module()
    bundle = _bundle()
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
                "text": "Relative density increased to 99.6% at higher VED.",
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


def test_cross_paper_finding_requires_two_direct_documents() -> None:
    checker = _load_module()
    result = checker.evaluate_objective_bundle(
        _bundle(level="cross_paper", paper_count=2),
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": "Relative density increased to 99.6% at higher VED.",
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "Finding finding-1 paper count matches direct evidence" in failed


def test_source_excerpt_mismatch_blocks_the_audit() -> None:
    checker = _load_module()
    result = checker.evaluate_objective_bundle(
        _bundle(),
        source_index={
            ("paper-1", "text_window", "block-1"): {
                "text": "A different source sentence.",
                "page": 4,
            }
        },
    )

    failed = {check["check"] for check in result["checks"] if check["status"] == "fail"}
    assert "all Evidence excerpts match Source artifacts" in failed
