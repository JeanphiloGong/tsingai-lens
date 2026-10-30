from dataclasses import replace

import pytest

from domain.core.comparison_group import ComparisonGroup, ComparisonGroupMember
from domain.core.finding import Finding
from domain.core.scientific_fact import ScientificContext


def _finding(status="single_study", groups=()):
    return Finding(
        collection_id="collection", objective_id="objective", analysis_version=1,
        finding_id="finding", statement="Preheat increases elongation.",
        factors=("preheat",), outcome="elongation", direction="increase",
        assertion_strength="associative", attribution_scope="association_only",
        synthesis_status=status, certainty=0.7, display_rank=0,
        mechanisms=(), scientific_context=ScientificContext(), limitations=(),
        paper_contributions=(), selection_ids=("selection-a", "selection-b"),
        comparison_group_ids=groups,
    )


def test_multiple_selections_of_one_experiment_are_not_independent_support():
    finding = _finding("agreement")
    with pytest.raises(ValueError, match="independent experiment"):
        finding.validate_experiment_support(frozenset({"experiment-a"}))
    replace(finding, synthesis_status="single_study").validate_experiment_support(
        frozenset({"experiment-a"})
    )


@pytest.mark.parametrize("status, groups, message", [
    ("agreement", (), "requires a comparison group"),
    ("single_study", ("group",), "cannot be single_study"),
])
def test_cross_experiment_conclusions_require_consistent_context(status, groups, message):
    with pytest.raises(ValueError, match=message):
        _finding(status, groups).validate_experiment_support(
            frozenset({"experiment-a", "experiment-b"})
        )


def test_independent_experiments_can_support_agreement():
    _finding("agreement", ("group",)).validate_experiment_support(
        frozenset({"experiment-a", "experiment-b"})
    )


def test_comparison_counts_only_included_independent_experiments():
    group = ComparisonGroup(
        group_id="group", objective_id="objective", analysis_version=1,
        outcome="elongation", comparison_target="within_paper_comparison",
        comparison_basis=("same method",), members=(
            ComparisonGroupMember("a", "included", "comparable", "same method"),
            ComparisonGroupMember("b", "included", "comparable", "same method"),
        ),
    )
    with pytest.raises(ValueError, match="multiple experiments"):
        group.validate_experiment_members({"a": "experiment-a", "b": "experiment-a"})
    group.validate_experiment_members({"a": "experiment-a", "b": "experiment-b"})
    context_only = replace(group, members=(group.members[0], replace(group.members[1], role="context")))
    with pytest.raises(ValueError, match="multiple experiments"):
        context_only.validate_experiment_members({"a": "experiment-a", "b": "experiment-b"})
