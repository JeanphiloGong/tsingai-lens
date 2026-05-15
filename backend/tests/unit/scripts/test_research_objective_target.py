from __future__ import annotations

import json
from pathlib import Path


TARGET_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "research_objective_targets"
    / "lpbf_slm_316l_collection_target.json"
)


def test_lpbf_slm_316l_target_has_required_contract_sections() -> None:
    target = _load_target()

    assert target["schema_version"] == "research_objective_target.v1"
    assert target["objective"]["question"]
    assert target["required_output_sections"] == [
        "objective",
        "evidence_scope",
        "paper_contributions",
        "sample_result_matrix",
        "controlled_comparisons",
        "mechanism_chains",
        "collection_conclusion",
        "limitations",
        "source_traceback",
    ]


def test_lpbf_slm_316l_target_preserves_expert_gold_scope() -> None:
    target = _load_target()

    assert target["expected_evidence_scope"] == {
        "paper_count": 6,
        "sample_count": 67,
        "test_condition_count": 27,
        "measurement_count": 362,
        "comparison_count": 88,
        "observation_count": 74,
        "uncertainty_count": 30,
    }


def test_lpbf_slm_316l_target_covers_all_gold_papers() -> None:
    target = _load_target()

    assert {
        contribution["paper_id"]
        for contribution in target["required_paper_contributions"]
    } == {"P001", "P002", "P003", "P004", "P005", "P006"}


def test_lpbf_slm_316l_target_claims_are_machine_checkable() -> None:
    target = _load_target()

    for claim in target["required_claims"]:
        assert claim["claim_id"]
        assert claim["text"]
        assert claim["required_papers"]
        assert claim.get("required_terms") or claim.get("required_numbers")


def test_lpbf_slm_316l_target_keeps_limits_and_forbidden_overclaims() -> None:
    target = _load_target()

    assert len(target["required_limitations"]) >= 5
    assert len(target["forbidden_overclaims"]) >= 5
    assert {
        limitation["paper_id"]
        for limitation in target["required_limitations"]
    } >= {"P001", "P003", "P005", "P006"}


def _load_target() -> dict:
    return json.loads(TARGET_PATH.read_text(encoding="utf-8"))
