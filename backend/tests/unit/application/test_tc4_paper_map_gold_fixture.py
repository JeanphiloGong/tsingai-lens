from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "fixtures"
    / "paper_map_policy"
    / "tc4_gold_baseline.json"
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_tc4_gold_fixture_contains_the_policy_comparison_scenarios():
    fixture = _fixture()

    assert fixture["schema_version"] == 1
    assert {
        scenario["id"] for scenario in fixture["scenarios"]
    } == {
        "multi_axis_experiment",
        "review_synthesis",
        "abstract_only_partial_map",
    }


def test_tc4_multi_axis_fixture_preserves_the_current_coverage_gap():
    scenario = next(
        item
        for item in _fixture()["scenarios"]
        if item["id"] == "multi_axis_experiment"
    )

    baseline_outcomes = {
        item["outcome"]
        for item in scenario["current_baseline"]["relationships"]
    }
    gold_outcomes = {
        item["outcome"] for item in scenario["gold_relationships"]
    }

    assert baseline_outcomes == {"porosity"}
    assert gold_outcomes == {
        "porosity",
        "grain morphology",
        "tensile strength",
    }
    assert set(scenario["current_baseline"]["uncovered_gold_outcomes"]) == (
        gold_outcomes - baseline_outcomes
    )
    assert scenario["current_baseline"]["expansion_count"] == 0


def test_tc4_review_and_sparse_scenarios_keep_uncertainty_explicit():
    scenarios = {item["id"]: item for item in _fixture()["scenarios"]}

    review = scenarios["review_synthesis"]
    assert review["gold_synthesis"]["cited_experiments_are_not_current_work"]
    assert review["current_baseline"]["current_work_relationships"] == 0

    sparse = scenarios["abstract_only_partial_map"]
    assert sparse["source_availability"] == "abstract_only"
    assert sparse["gold_scope"]["status"] == "partial_map"
    assert "exact parameter levels" in sparse["do_not_infer"]
