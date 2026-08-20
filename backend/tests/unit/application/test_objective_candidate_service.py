from __future__ import annotations

from itertools import permutations
from typing import Any

import pytest

from application.core.objectives.discovery.axis_equivalence import (
    StructuredAxisCanonicalizationPlan,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from domain.core import PaperSkim, ResearchObjective


class _GroupingExtractor:
    def __init__(self) -> None:
        self.canonicalization_payloads: list[dict[str, Any]] = []

    def classify(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            decisions=[
                {
                    "pair_id": pair["pair_id"],
                    "equivalent": True,
                    "same_research_topic": True,
                }
                for pair in payload.get("axis_pairs", ())
            ]
        )


def test_relationship_groups_preserve_complete_study_relationship_records():
    skim = _paper_skim(
        document_id="paper-1",
        relationship_id="relationship-density",
        factors=("laser power", "scan speed"),
        outcome="relative density",
        material_scope=("316L stainless steel",),
        process_context=("laser powder bed fusion",),
        sample_context=("vertical tensile coupon",),
        test_context=("Archimedes density",),
        fixed_conditions=("layer thickness 30 um",),
        comparator="lowest versus highest energy input",
    )

    groups = ObjectiveCandidateService()._build_relationship_groups(
        (skim,),
    )

    assert len(groups) == 1
    assert groups[0] == [
        {
            "document_id": "paper-1",
            "doc_role": "experimental",
            "study": {
                "study_id": "study-paper-1",
                "document_id": "paper-1",
                "design_type": "experimental",
                "claim_scope": "current_work",
                "experiment_label": "experiment paper-1",
                "material_scope": ["316L stainless steel"],
                "process_context": ["laser powder bed fusion"],
                "sample_context": ["vertical tensile coupon"],
                "test_context": ["Archimedes density"],
                "comparator": "lowest versus highest energy input",
                "fixed_conditions": ["layer thickness 30 um"],
                "confidence": 0.92,
            },
            "relationship": {
                "relationship_id": "relationship-density",
                "varied_factors": ["laser power", "scan speed"],
                "outcome": "relative density",
                "source_refs": [
                    {"source_kind": "block", "source_ref": "paper-1-results"}
                ],
                "confidence": 0.9,
            },
            "evidence_density": "high",
            "paper_confidence": 0.91,
            "warnings": [],
        }
    ]


def test_possible_unknown_context_cannot_bridge_conflicting_material_anchors():
    skims = (
        _paper_skim(
            document_id="paper-a",
            relationship_id="relationship-a",
            material_scope=("316L stainless steel",),
        ),
        _paper_skim(
            document_id="paper-b",
            relationship_id="relationship-b",
            material_scope=(),
        ),
        _paper_skim(
            document_id="paper-c",
            relationship_id="relationship-c",
            material_scope=("Ti-6Al-4V",),
        ),
    )
    service = ObjectiveCandidateService()

    expected_groups: list[tuple[str, ...]] | None = None
    for ordering in permutations(skims):
        groups = _group_relationship_ids(service._build_relationship_groups(ordering))
        if expected_groups is None:
            expected_groups = groups
        assert groups == expected_groups
        assert all(
            not {"relationship-a", "relationship-c"}.issubset(group) for group in groups
        )

    assert expected_groups == [
        ("relationship-a",),
        ("relationship-b",),
        ("relationship-c",),
    ]


def test_missing_material_attaches_to_one_unambiguous_known_material_group():
    skims = (
        _paper_skim(
            document_id="paper-known",
            relationship_id="relationship-known",
            material_scope=("316L stainless steel",),
        ),
        _paper_skim(
            document_id="paper-missing",
            relationship_id="relationship-missing",
            material_scope=(),
        ),
    )

    groups = _group_relationship_ids(
        ObjectiveCandidateService()._build_relationship_groups(skims)
    )

    assert groups == [("relationship-known", "relationship-missing")]


def test_missing_material_and_one_known_anchor_build_cross_paper_objective():
    skims = (
        _paper_skim(
            document_id="paper-known",
            relationship_id="relationship-known",
            material_scope=("316L stainless steel",),
        ),
        _paper_skim(
            document_id="paper-missing",
            relationship_id="relationship-missing",
            material_scope=(),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.material_scope == ("316L stainless steel",)
    assert set(objective.seed_document_ids) == {"paper-known", "paper-missing"}
    assert set(objective.source_relationship_ids) == {
        "relationship-known",
        "relationship-missing",
    }
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}


def test_missing_material_does_not_inherit_an_ambiguous_multi_material_scope():
    skims = (
        _paper_skim(
            document_id="paper-multi-material",
            relationship_id="relationship-known",
            material_scope=("316L stainless steel", "Ti-6Al-4V"),
        ),
        _paper_skim(
            document_id="paper-missing",
            relationship_id="relationship-missing",
            material_scope=(),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.material_scope == ()
    assert objective.reason is not None
    assert "No unambiguous shared material scope was available" in objective.reason


def test_missing_confidence_does_not_erase_supported_objective_confidence():
    skims = (
        _paper_skim(
            document_id="paper-study-confidence-missing",
            relationship_id="relationship-known",
            study_confidence=0.0,
            relationship_confidence=0.86,
        ),
        _paper_skim(
            document_id="paper-relationship-confidence-missing",
            relationship_id="relationship-missing",
            study_confidence=0.82,
            relationship_confidence=0.0,
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    assert facts.research_objectives[0].confidence == pytest.approx(0.82)


def test_all_missing_confidence_remains_zero_with_an_explicit_reason():
    skims = (
        _paper_skim(
            document_id="paper-a",
            relationship_id="relationship-a",
            study_confidence=0.0,
            relationship_confidence=0.0,
        ),
        _paper_skim(
            document_id="paper-b",
            relationship_id="relationship-b",
            study_confidence=0.0,
            relationship_confidence=0.0,
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.confidence == 0.0
    assert objective.reason is not None
    assert "No source supplied a non-zero confidence" in objective.reason


def test_broad_outcome_group_is_rejected_until_the_outcome_is_specific():
    skims = (
        _paper_skim(
            document_id="paper-a",
            relationship_id="relationship-a",
            outcome="mechanical properties",
        ),
        _paper_skim(
            document_id="paper-b",
            relationship_id="relationship-b",
            outcome="mechanical properties",
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert facts.research_objectives == ()
    assert {item.status.value for item in facts.study_dispositions} == {"rejected"}
    assert all(
        "requires a specific measurable outcome" in (item.reason or "")
        for item in facts.study_dispositions
    )


def test_single_measurement_broad_outcome_is_refined_for_the_candidate():
    skims = (
        _paper_skim(
            document_id="paper-a",
            relationship_id="relationship-a",
            outcome="densification",
        ),
        _paper_skim(
            document_id="paper-b",
            relationship_id="relationship-b",
            outcome="densification",
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.question == "How does laser power affect relative density?"
    assert objective.outcomes == ("relative density",)
    assert set(objective.source_relationship_ids) == {
        "relationship-a",
        "relationship-b",
    }


def test_material_grade_word_order_does_not_fragment_relationship_groups():
    skims = (
        _paper_skim(
            document_id="paper-long-form",
            relationship_id="relationship-long-form",
            material_scope=("316L stainless steel",),
        ),
        _paper_skim(
            document_id="paper-reordered",
            relationship_id="relationship-reordered",
            material_scope=("stainless steel 316L",),
        ),
    )

    groups = _group_relationship_ids(
        ObjectiveCandidateService()._build_relationship_groups(skims)
    )

    assert groups == [
        ("relationship-long-form", "relationship-reordered"),
    ]


def test_material_grade_word_order_preserves_shared_objective_material_scope():
    class RejectingAxisExtractor(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": False,
                        "same_research_topic": False,
                    }
                    for pair in payload.get("axis_pairs", ())
                ]
            )

    skims = (
        _paper_skim(
            document_id="paper-long-form",
            relationship_id="relationship-long-form",
            material_scope=("316L stainless steel",),
        ),
        _paper_skim(
            document_id="paper-reordered",
            relationship_id="relationship-reordered",
            material_scope=("stainless steel 316L",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=RejectingAxisExtractor(),
    )

    assert len(facts.research_objectives) == 1
    assert facts.research_objectives[0].material_scope == ("316L stainless steel",)


def test_two_relationships_with_missing_material_context_share_one_group():
    skims = (
        _paper_skim(
            document_id="paper-a",
            relationship_id="relationship-a",
            material_scope=(),
        ),
        _paper_skim(
            document_id="paper-b",
            relationship_id="relationship-b",
            material_scope=(),
        ),
    )

    groups = _group_relationship_ids(
        ObjectiveCandidateService()._build_relationship_groups(skims)
    )

    assert groups == [("relationship-a", "relationship-b")]


def test_explicit_axis_synonyms_remain_in_one_compatible_group():
    skims = (
        _paper_skim(
            document_id="paper-scan",
            relationship_id="relationship-scan",
            factors=("scan strategy",),
            outcome="UTS",
        ),
        _paper_skim(
            document_id="paper-scanning",
            relationship_id="relationship-scanning",
            factors=("scanning strategy",),
            outcome="ultimate tensile strength",
        ),
    )

    groups = _group_relationship_ids(
        ObjectiveCandidateService()._build_relationship_groups(skims)
    )

    assert groups == [
        ("relationship-scan", "relationship-scanning"),
    ]


@pytest.mark.parametrize(
    ("changed_field", "left_value", "right_value"),
    (
        ("process_context", ("LPBF",), ("directed energy deposition",)),
        ("design_type", "experimental", "modeling"),
        ("comparator", "as-built vs aged", "as-built vs annealed"),
        ("sample_context", ("vertical coupon",), ("horizontal coupon",)),
        ("test_context", ("tensile test",), ("compression test",)),
        ("fixed_conditions", ("200 C",), ("400 C",)),
    ),
)
def test_study_context_differences_do_not_fragment_objective_membership(
    changed_field: str,
    left_value: Any,
    right_value: Any,
):
    common = {
        "material_scope": ("316L stainless steel",),
        "process_context": ("LPBF",),
        "sample_context": ("vertical coupon",),
        "test_context": ("tensile test",),
        "fixed_conditions": ("argon atmosphere",),
        "design_type": "experimental",
        "claim_scope": "current_work",
        "comparator": "low versus high setting",
    }
    left_context = {**common, changed_field: left_value}
    right_context = {**common, changed_field: right_value}
    skims = (
        _paper_skim(
            document_id="paper-left",
            relationship_id="relationship-left",
            **left_context,
        ),
        _paper_skim(
            document_id="paper-right",
            relationship_id="relationship-right",
            **right_context,
        ),
    )

    groups = _group_relationship_ids(
        ObjectiveCandidateService()._build_relationship_groups(skims)
    )

    assert groups == [("relationship-left", "relationship-right")]


def test_different_fixed_condition_values_remain_in_one_objective_group():
    skims = (
        _paper_skim(
            document_id="paper-200-c",
            relationship_id="relationship-200-c",
            fixed_conditions=("temperature (200 C)",),
        ),
        _paper_skim(
            document_id="paper-400-c",
            relationship_id="relationship-400-c",
            fixed_conditions=("temperature (400 C)",),
        ),
    )

    groups = _group_relationship_ids(
        ObjectiveCandidateService()._build_relationship_groups(skims)
    )

    assert groups == [("relationship-200-c", "relationship-400-c")]


def test_single_and_joint_factor_relationships_share_a_topic_without_losing_factors():
    skims = (
        _paper_skim(
            document_id="paper-single",
            relationship_id="relationship-single",
            factors=("laser power",),
        ),
        _paper_skim(
            document_id="paper-joint",
            relationship_id="relationship-joint",
            factors=("laser power", "scan speed"),
        ),
    )

    groups = _group_relationship_ids(
        ObjectiveCandidateService()._build_relationship_groups(skims)
    )

    assert groups == [("relationship-joint", "relationship-single")]
    assert skims[0].studies[0].relationships[0].varied_factors == ("laser power",)
    assert skims[1].studies[0].relationships[0].varied_factors == (
        "laser power",
        "scan speed",
    )


def test_topic_supported_thermal_relationships_do_not_cross_processing_stage():
    class ThermalTopicClassifier(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            decisions = []
            for pair in payload["axis_pairs"]:
                labels = {pair["left"], pair["right"]}
                equivalent = (
                    labels
                    in (
                        {"Ti-6Al-4V", "Ti6Al4V"},
                        {"microstructure", "microstructure morphology"},
                    )
                    and pair["axis_type"] == "material"
                )
                same_topic = (
                    equivalent
                    or (
                        pair["axis_type"] == "variable"
                        and labels
                        <= {
                            "heat treatment temperature",
                            "heat treatment duration",
                            "annealing temperature",
                            "base plate preheating temperature",
                        }
                    )
                    or (
                        pair["axis_type"] == "outcome"
                        and labels == {"microstructure", "microstructure morphology"}
                    )
                )
                decisions.append(
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": equivalent,
                        "same_research_topic": same_topic,
                    }
                )
            return StructuredAxisCanonicalizationPlan(decisions=decisions)

    skims = (
        _paper_skim(
            document_id="paper-heat-treatment",
            relationship_id="relationship-heat-treatment",
            factors=("heat treatment temperature", "heat treatment duration"),
            outcome="microstructure",
            material_scope=("Ti-6Al-4V",),
            process_context=("SLM", "post-build heat treatment"),
        ),
        _paper_skim(
            document_id="paper-annealing",
            relationship_id="relationship-annealing",
            factors=("annealing temperature",),
            outcome="microstructure",
            material_scope=("Ti6Al4V",),
            process_context=("SLM", "post-build annealing"),
        ),
        _paper_skim(
            document_id="paper-preheating",
            relationship_id="relationship-preheating",
            factors=("base plate preheating temperature",),
            outcome="microstructure",
            material_scope=("Ti-6Al-4V",),
            process_context=("SLM", "in-process preheating"),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-ti64",
        paper_skims=skims,
        axis_equivalence_classifier=ThermalTopicClassifier(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert set(objective.seed_document_ids) == {
        "paper-heat-treatment",
        "paper-annealing",
    }
    assert set(objective.source_relationship_ids) == {
        "relationship-heat-treatment",
        "relationship-annealing",
    }
    assert "base plate preheating temperature" not in objective.variables
    assert objective.outcomes == ("microstructure",)
    assert objective.material_scope in (("Ti-6Al-4V",), ("Ti6Al4V",))
    assert {
        item.status.value
        for item in facts.study_dispositions
        if item.relationship_id == "relationship-preheating"
    } == {"rejected"}
    assert skims[0].studies[0].relationships[0].varied_factors == (
        "heat treatment temperature",
        "heat treatment duration",
    )


def test_objective_question_keeps_only_axes_supported_across_papers():
    class CoolingTopicClassifier(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": False,
                        "same_research_topic": (
                            pair["axis_type"] == "variable"
                            and {pair["left"], pair["right"]}
                            == {"cooling rate after HIP", "HIP cooling rate"}
                        ),
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_skim(
            document_id="paper-hip-methods",
            relationship_id="relationship-hip-methods",
            factors=(
                "cooling rate after HIP",
                "HIP temperature",
                "parent beta grain size",
            ),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_skim(
            document_id="paper-hip-results",
            relationship_id="relationship-hip-results",
            factors=("HIP cooling rate", "post-processing route"),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-ti64-cooling",
        paper_skims=skims,
        axis_equivalence_classifier=CoolingTopicClassifier(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert set(objective.variables) == {
        "cooling rate after HIP",
        "HIP cooling rate",
    }
    assert set(objective.source_relationship_ids) == {
        "relationship-hip-methods",
        "relationship-hip-results",
    }
    assert skims[0].studies[0].relationships[0].varied_factors == (
        "cooling rate after HIP",
        "HIP temperature",
        "parent beta grain size",
    )


def test_local_topic_bridges_do_not_form_one_multi_topic_objective():
    topic_pairs = {
        frozenset(("cooling rate after HIP", "HIP cooling rate")),
        frozenset(("HIP temperature", "heat treatment temperature")),
        frozenset(("post-processing route", "scan strategy")),
    }

    class LocalTopicClassifier(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": False,
                        "same_research_topic": (
                            pair["axis_type"] == "variable"
                            and frozenset((pair["left"], pair["right"])) in topic_pairs
                        ),
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_skim(
            document_id="paper-a",
            relationship_id="relationship-a",
            factors=("cooling rate after HIP", "HIP temperature"),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_skim(
            document_id="paper-b",
            relationship_id="relationship-b",
            factors=("HIP cooling rate", "post-processing route"),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_skim(
            document_id="paper-c",
            relationship_id="relationship-c",
            factors=("heat treatment temperature", "scan strategy"),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-local-topic-bridges",
        paper_skims=skims,
        axis_equivalence_classifier=LocalTopicClassifier(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert len(objective.variables) == 2
    assert len(objective.seed_document_ids) == 2
    assert len(objective.source_relationship_ids) == 2
    assert all(
        disposition.status.value == "promoted"
        for disposition in facts.study_dispositions
        if disposition.relationship_id in objective.source_relationship_ids
    )
    assert (
        sum(
            disposition.status.value == "rejected"
            for disposition in facts.study_dispositions
        )
        == 1
    )


def test_axis_topic_classifier_receives_bounded_study_usage_context():
    class ContextAwareClassifier(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            decisions = []
            for pair in payload["axis_pairs"]:
                labels = {pair["left"], pair["right"]}
                same_topic = labels == {"build orientation", "sample orientation"}
                if pair["axis_type"] == "variable":
                    assert pair["left_observations"]
                    assert pair["right_observations"]
                    for side in ("left", "right"):
                        for observation in pair[f"{side}_observations"]:
                            assert pair[side] in observation["varied_factors"]
                            assert len(observation["varied_factors"]) <= 6
                            assert len(observation["process_context"]) <= 2
                            assert len(observation["sample_context"]) <= 2
                            assert all(
                                len(value) <= 120
                                for values in observation.values()
                                for value in values
                            )
                decisions.append(
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": False,
                        "same_research_topic": same_topic,
                    }
                )
            return StructuredAxisCanonicalizationPlan(decisions=decisions)

    skims = (
        _paper_skim(
            document_id="paper-build",
            relationship_id="relationship-build",
            factors=(
                "build orientation",
                "laser speed",
                "laser power",
                "gauge cross section",
                "layer thickness",
                "hatch spacing",
                "scan rotation",
            ),
            outcome="ultimate tensile strength",
            process_context=(
                "laser powder bed fusion",
                "laser exposure parameters",
                "post-build stress relief",
            ),
            sample_context=(
                "vertical build direction",
                "horizontal build direction",
                "two gauge geometries",
            ),
        ),
        _paper_skim(
            document_id="paper-orientation",
            relationship_id="relationship-orientation",
            factors=("sample orientation",),
            outcome="ultimate tensile strength",
            process_context=("laser powder bed fusion",),
            sample_context=(
                "tensile axis parallel to build direction",
                "tensile axis perpendicular to build direction",
            ),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-orientation",
        paper_skims=skims,
        axis_equivalence_classifier=ContextAwareClassifier(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert set(objective.variables) == {"build orientation", "sample orientation"}
    assert "laser speed" not in objective.question
    assert skims[0].studies[0].relationships[0].varied_factors == (
        "build orientation",
        "laser speed",
        "laser power",
        "gauge cross section",
        "layer thickness",
        "hatch spacing",
        "scan rotation",
    )


def test_topic_only_pairs_are_confirmed_in_bounded_batches():
    class BatchBiasedClassifier(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            is_confirmation = payload.get("decision_stage") == "topic_confirmation"
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": False,
                        "same_research_topic": (
                            not is_confirmation
                            or {pair["left"], pair["right"]}
                            == {"build orientation", "sample orientation"}
                        ),
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    classifier = BatchBiasedClassifier()
    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-confirm-topic",
        paper_skims=(
            _paper_skim(
                document_id="paper-build",
                relationship_id="relationship-build",
                factors=("build orientation",),
                outcome="ultimate tensile strength",
            ),
            _paper_skim(
                document_id="paper-laser",
                relationship_id="relationship-laser",
                factors=("tensile orientation",),
                outcome="ultimate tensile strength",
            ),
            _paper_skim(
                document_id="paper-sample",
                relationship_id="relationship-sample",
                factors=("sample orientation",),
                outcome="ultimate tensile strength",
            ),
        ),
        axis_equivalence_classifier=classifier,
    )

    initial_payloads = [
        payload
        for payload in classifier.canonicalization_payloads
        if payload.get("decision_stage") != "topic_confirmation"
    ]
    confirmation_payloads = [
        payload
        for payload in classifier.canonicalization_payloads
        if payload.get("decision_stage") == "topic_confirmation"
    ]
    assert len(initial_payloads) == 1
    assert len(initial_payloads[0]["axis_pairs"]) == 3
    assert len(confirmation_payloads) == 1
    assert len(confirmation_payloads[0]["axis_pairs"]) == 3
    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert set(objective.variables) == {"build orientation", "sample orientation"}
    assert set(objective.seed_document_ids) == {"paper-build", "paper-sample"}
    assert (
        next(
            item
            for item in facts.study_dispositions
            if item.relationship_id == "relationship-laser"
        ).status.value
        == "rejected"
    )


def test_different_measured_outcomes_never_share_an_objective_group():
    skims = (
        _paper_skim(
            document_id="paper-porosity",
            relationship_id="relationship-porosity",
            outcome="porosity",
        ),
        _paper_skim(
            document_id="paper-density",
            relationship_id="relationship-density",
            outcome="relative density",
        ),
    )

    groups = _group_relationship_ids(
        ObjectiveCandidateService()._build_relationship_groups(skims)
    )

    assert groups == [
        ("relationship-density",),
        ("relationship-porosity",),
    ]


def test_topic_related_but_distinct_outcomes_do_not_form_one_objective():
    class RelatedOutcomeClassifier(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": False,
                        "same_research_topic": True,
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_skim(
            document_id="paper-microstructure",
            relationship_id="relationship-microstructure",
            factors=("annealing temperature",),
            outcome="microstructure",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_skim(
            document_id="paper-strength",
            relationship_id="relationship-strength",
            factors=("annealing temperature",),
            outcome="yield strength",
            material_scope=("Ti6Al4V",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-focused-outcome",
        paper_skims=skims,
        axis_equivalence_classifier=RelatedOutcomeClassifier(),
    )

    assert facts.research_objectives == ()
    assert {item.status.value for item in facts.study_dispositions} == {"rejected"}


def test_cross_paper_outcome_alias_can_be_canonicalized_without_topic_merging():
    class MartensiteAliasClassifier(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": pair["axis_type"] == "outcome",
                        "same_research_topic": pair["axis_type"] == "outcome",
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_skim(
            document_id="paper-alpha-prime",
            relationship_id="relationship-alpha-prime",
            factors=("heat treatment condition",),
            outcome="alpha-prime fraction",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_skim(
            document_id="paper-martensite",
            relationship_id="relationship-martensite",
            factors=("heat treatment condition",),
            outcome="martensite fraction",
            material_scope=("Ti6Al4V",),
        ),
    )
    classifier = MartensiteAliasClassifier()

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-outcome-alias",
        paper_skims=skims,
        axis_equivalence_classifier=classifier,
    )

    assert len(facts.research_objectives) == 1
    assert facts.research_objectives[0].outcomes in (
        ("alpha-prime fraction",),
        ("martensite fraction",),
    )
    assert any(
        pair["axis_type"] == "outcome"
        and {pair["left"], pair["right"]}
        == {"alpha-prime fraction", "martensite fraction"}
        for payload in classifier.canonicalization_payloads
        for pair in payload["axis_pairs"]
    )


def test_joint_factors_are_indivisible_and_each_outcome_is_accounted_separately():
    skim = _paper_skim(
        document_id="paper-1",
        relationship_id="relationship-density",
        factors=("laser power", "scan speed"),
        outcome="relative density",
        extra_relationships=(
            {
                "relationship_id": "relationship-porosity",
                "varied_factors": ["laser power", "scan speed"],
                "outcome": "porosity",
                "source_refs": [
                    {"source_kind": "table", "source_ref": "paper-1-table"}
                ],
                "confidence": 0.88,
            },
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=(skim,),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert {objective.variables for objective in facts.research_objectives} == {
        ("laser power", "scan speed"),
    }
    assert {objective.outcomes for objective in facts.research_objectives} == {
        ("relative density",),
        ("porosity",),
    }
    assert {
        relationship_id
        for objective in facts.research_objectives
        for relationship_id in objective.source_relationship_ids
    } == {"relationship-density", "relationship-porosity"}
    assert len(facts.study_dispositions) == 2
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}


def test_multi_paper_collection_does_not_promote_single_paper_relationships():
    skims = (
        _paper_skim(
            document_id="paper-steel",
            relationship_id="relationship-steel",
            material_scope=("316L stainless steel",),
        ),
        _paper_skim(
            document_id="paper-ti",
            relationship_id="relationship-ti",
            material_scope=("Ti-6Al-4V",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert facts.research_objectives == ()
    assert {item.status.value for item in facts.study_dispositions} == {"rejected"}
    assert all(
        item.reason == "Relationship is not supported by multiple collection papers."
        for item in facts.study_dispositions
    )


def test_candidate_build_derives_objective_identity_and_lineage_from_relationships():
    skims = tuple(
        _paper_skim(
            document_id=f"paper-{index}",
            relationship_id=f"relationship-{index}",
        )
        for index in range(3)
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.question == "How does laser power affect relative density?"
    assert objective.variables == ("laser power",)
    assert objective.outcomes == ("relative density",)
    assert objective.seed_document_ids == ("paper-0", "paper-1", "paper-2")
    assert set(objective.source_relationship_ids) == {
        "relationship-0",
        "relationship-1",
        "relationship-2",
    }
    assert len(facts.study_dispositions) == 3
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}


def test_fallback_consolidation_keeps_context_differences_on_paper_studies():
    skims = (
        _paper_skim(
            document_id="paper-a",
            relationship_id="relationship-a",
            process_context=("context alpha",),
            sample_context=("context beta",),
        ),
        _paper_skim(
            document_id="paper-b",
            relationship_id="relationship-b",
            process_context=("context beta",),
            sample_context=("context alpha",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert "context alpha" not in objective.constraints
    assert "context beta" not in objective.constraints
    assert facts.paper_skims[0].studies[0].process_context == ("context alpha",)
    assert facts.paper_skims[1].studies[0].process_context == ("context beta",)
    assert {
        relationship_id
        for objective in facts.research_objectives
        for relationship_id in objective.source_relationship_ids
    } == {"relationship-a", "relationship-b"}
    assert [item.relationship_id for item in facts.study_dispositions] == [
        "relationship-a",
        "relationship-b",
    ]
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}


def test_compatible_relationship_group_builds_one_cross_paper_objective():
    skims = tuple(
        _paper_skim(
            document_id=f"paper-{index}",
            relationship_id=f"relationship-{index}",
        )
        for index in range(3)
    )
    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    assert set(facts.research_objectives[0].source_relationship_ids) == {
        "relationship-0",
        "relationship-1",
        "relationship-2",
    }
    assert facts.research_objectives[0].seed_document_ids == (
        "paper-0",
        "paper-1",
        "paper-2",
    )


@pytest.mark.parametrize("claim_scope", ("synthesis", "background"))
def test_non_current_work_relationships_remain_in_inventory_without_seeding_objectives(
    claim_scope: str,
):
    skim = _paper_skim(
        document_id="paper-review",
        relationship_id="relationship-review",
        claim_scope=claim_scope,
    )
    extractor = _GroupingExtractor()

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=(skim,),
        axis_equivalence_classifier=extractor,
    )

    assert facts.paper_skims == (skim,)
    assert facts.research_objectives == ()
    assert len(facts.study_dispositions) == 1
    disposition = facts.study_dispositions[0]
    assert disposition.relationship_id == "relationship-review"
    assert disposition.status.value == "rejected"
    assert claim_scope in str(disposition.reason)


def test_uncertain_claim_scope_is_retained_as_a_standalone_candidate():
    skim = _paper_skim(
        document_id="paper-uncertain",
        relationship_id="relationship-uncertain",
        claim_scope="uncertain",
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=(skim,),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert facts.research_objectives[0].source_relationship_ids == (
        "relationship-uncertain",
    )
    assert facts.study_dispositions[0].status.value == "promoted"


def test_axis_canonicalization_retains_valid_groups_and_defaults_missing_axes():
    class IncompleteAxisPlanExtractor(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            diameter_pair = next(
                pair["pair_id"]
                for pair in payload["axis_pairs"]
                if {pair["left"], pair["right"]}
                == {"maximum defect diameter", "max defect diameter"}
            )
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": pair["pair_id"] == diameter_pair,
                        "same_research_topic": pair["pair_id"] == diameter_pair,
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_skim(
            document_id="paper-1",
            relationship_id="relationship-1",
            outcome="maximum defect diameter",
        ),
        _paper_skim(
            document_id="paper-2",
            relationship_id="relationship-2",
            outcome="max defect diameter",
        ),
        _paper_skim(
            document_id="paper-3",
            relationship_id="relationship-3",
            outcome="max defect length",
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=IncompleteAxisPlanExtractor(),
    )

    assert {objective.outcomes for objective in facts.research_objectives} == {
        ("max defect diameter",),
    }
    diameter_objective = next(
        objective
        for objective in facts.research_objectives
        if objective.outcomes == ("max defect diameter",)
    )
    assert set(diameter_objective.source_relationship_ids) == {
        "relationship-1",
        "relationship-2",
    }
    length_disposition = next(
        item
        for item in facts.study_dispositions
        if item.relationship_id == "relationship-3"
    )
    assert length_disposition.status.value == "rejected"
    assert (
        length_disposition.reason
        == "Relationship is not supported by multiple collection papers."
    )


def test_result_clause_outcome_is_not_promoted_as_an_axis_alias():
    class SemanticAxisExtractor(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": True,
                        "same_research_topic": True,
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_skim(
            document_id="paper-result-clause",
            relationship_id="relationship-result-clause",
            factors=("VED",),
            outcome="fatigue strength decreases with lower VED",
            fixed_conditions=("as built",),
        ),
        _paper_skim(
            document_id="paper-neutral-axis",
            relationship_id="relationship-neutral-axis",
            factors=("volumetric energy density",),
            outcome="fatigue strength",
            fixed_conditions=("stress relieved",),
        ),
    )
    extractor = SemanticAxisExtractor()

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=extractor,
    )

    assert facts.research_objectives == ()
    assert facts.paper_skims == skims
    assert len(facts.study_dispositions) == 2
    assert {item.status.value for item in facts.study_dispositions} == {"rejected"}


def test_material_and_axis_aliases_build_one_cross_paper_objective():
    class MaterialAxisExtractor(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": {pair["left"], pair["right"]}
                        in (
                            {"316L stainless steel", "SS316L"},
                            {"scan speed", "laser scanning speed"},
                        ),
                        "same_research_topic": True,
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_skim(
            document_id="paper-long-form",
            relationship_id="relationship-long-form",
            factors=("laser power", "scan speed"),
            outcome="porosity",
            material_scope=("316L stainless steel",),
        ),
        _paper_skim(
            document_id="paper-short-form",
            relationship_id="relationship-short-form",
            factors=("laser power", "laser scanning speed"),
            outcome="porosity",
            material_scope=("SS316L",),
        ),
    )
    extractor = MaterialAxisExtractor()

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=extractor,
    )

    assert {
        (pair["axis_type"], pair["left"], pair["right"])
        for pair in extractor.canonicalization_payloads[0]["axis_pairs"]
    } >= {
        ("variable", "scan speed", "laser scanning speed"),
    }
    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.variables == ("laser power", "scan speed")
    assert objective.outcomes == ("porosity",)
    assert objective.material_scope == ("316L stainless steel",)
    assert set(objective.seed_document_ids) == {
        "paper-long-form",
        "paper-short-form",
    }
    assert set(objective.source_relationship_ids) == {
        "relationship-long-form",
        "relationship-short-form",
    }
    assert facts.paper_skims == skims
    assert facts.paper_skims[1].studies[0].material_scope == ("SS316L",)


def test_objective_constraints_omit_the_relationship_axes():
    skim = _paper_skim(
        document_id="paper-heat-treatment",
        relationship_id="relationship-heat-treatment",
        factors=("heat treatment",),
        outcome="microstructure",
        process_context=("LPBF", "heat treatment"),
        test_context=("microstructure", "EBSD"),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=(skim,),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.constraints == (
        "LPBF",
        "vertical coupon",
        "EBSD",
        "argon atmosphere",
        "experimental",
        "current_work",
    )
    assert facts.study_dispositions[0].status.value == "promoted"


def test_verified_aliases_are_consistent_through_context_and_canonicalization():
    skims = (
        _paper_skim(
            document_id="paper-scan",
            relationship_id="relationship-scan",
            factors=("scan strategy",),
            outcome="UTS",
        ),
        _paper_skim(
            document_id="paper-scanning",
            relationship_id="relationship-scanning",
            factors=("scanning strategy",),
            outcome="ultimate tensile strength",
        ),
    )
    service = ObjectiveCandidateService()

    assert _group_relationship_ids(service._build_relationship_groups(skims)) == [
        ("relationship-scan", "relationship-scanning")
    ]

    axis_candidates = {
        "material": [],
        "variable": ["scan strategy", "scanning strategy"],
        "outcome": ["UTS", "ultimate tensile strength"],
    }
    axis_pairs = service._build_axis_candidate_pairs(axis_candidates)
    plan = StructuredAxisCanonicalizationPlan(
        decisions=[
            {
                "pair_id": pair_id,
                "equivalent": True,
                "same_research_topic": True,
            }
            for pair_id in axis_pairs
        ]
    )
    inventory = service._relationship_inventory(skims)
    assert service._axis_mapping_from_plan(
        plan,
        axis_candidates=axis_candidates,
        axis_pairs=axis_pairs,
        relationship_inventory=inventory,
    ) == {
        "material": {},
        "variable": {
            "scan strategy": "scan strategy",
            "scanning strategy": "scan strategy",
        },
        "outcome": {
            "uts": "ultimate tensile strength",
            "ultimate tensile strength": "ultimate tensile strength",
        },
    }


def test_axis_pair_selection_keeps_every_eligible_pair_and_complete_link_is_order_stable():
    service = ObjectiveCandidateService()
    crowded_candidates = {
        "material": [],
        "variable": [f"scan speed variant {index:03d}" for index in range(40)],
        "outcome": [],
    }

    assert len(service._build_axis_candidate_pairs(crowded_candidates)) == 780

    inventory = service._relationship_inventory(
        (
            _paper_skim(
                document_id="paper-a",
                relationship_id="relationship-a",
                outcome="mechanical properties",
            ),
            _paper_skim(
                document_id="paper-b",
                relationship_id="relationship-b",
                outcome="yield strength",
            ),
            _paper_skim(
                document_id="paper-c",
                relationship_id="relationship-c",
                outcome="ultimate tensile strength",
            ),
        )
    )
    axis_pairs = {
        "axis_pair_0001": (
            "outcome",
            "mechanical properties",
            "yield strength",
        ),
        "axis_pair_0002": (
            "outcome",
            "mechanical properties",
            "ultimate tensile strength",
        ),
    }
    plan = StructuredAxisCanonicalizationPlan(
        decisions=[
            {
                "pair_id": pair_id,
                "equivalent": True,
                "same_research_topic": True,
            }
            for pair_id in axis_pairs
        ]
    )
    mappings = [
        service._axis_mapping_from_plan(
            plan,
            axis_candidates={
                "material": [],
                "variable": [],
                "outcome": list(order),
            },
            axis_pairs=axis_pairs,
            relationship_inventory=inventory,
        )
        for order in permutations(
            (
                "mechanical properties",
                "yield strength",
                "ultimate tensile strength",
            )
        )
    ]

    assert all(mapping == mappings[0] for mapping in mappings)
    assert len(set(mappings[0]["outcome"].values())) == 2


def test_cross_paper_topic_candidates_require_a_focused_shared_signal():
    skims = (
        _paper_skim(
            document_id="paper-heat",
            relationship_id="relationship-heat",
            factors=("heat treatment temperature",),
            outcome="elongation",
            process_context=("LPBF", "post-build heat treatment"),
        ),
        _paper_skim(
            document_id="paper-anneal",
            relationship_id="relationship-anneal",
            factors=("annealing duration",),
            outcome="elongation",
            process_context=("SLM", "post-build annealing"),
        ),
        _paper_skim(
            document_id="paper-preheat",
            relationship_id="relationship-preheat",
            factors=("base plate preheating temperature",),
            outcome="elongation",
            process_context=("LPBF", "in-process preheating"),
        ),
        _paper_skim(
            document_id="paper-orientation",
            relationship_id="relationship-orientation",
            factors=("build orientation",),
            outcome="elongation",
            process_context=("LPBF",),
        ),
    )
    service = ObjectiveCandidateService()

    supported = service._supported_cross_paper_axis_pairs(
        service._relationship_inventory(skims)
    )

    assert supported == {
        service._axis_relation_key(
            "variable",
            "heat treatment temperature",
            "annealing duration",
        )
    }


def test_shared_variable_does_not_propose_unrelated_outcome_pairs():
    skims = (
        _paper_skim(
            document_id="paper-strength",
            relationship_id="relationship-strength",
            outcome="yield strength",
        ),
        _paper_skim(
            document_id="paper-ductility",
            relationship_id="relationship-ductility",
            outcome="elongation",
        ),
        _paper_skim(
            document_id="paper-structure",
            relationship_id="relationship-structure",
            outcome="microstructure",
        ),
    )
    service = ObjectiveCandidateService()

    supported = service._supported_cross_paper_axis_pairs(
        service._relationship_inventory(skims)
    )

    assert not {pair for pair in supported if pair[0] == "outcome"}


def test_axis_pair_classification_batches_account_for_every_pair_once():
    class RecordingExtractor(_GroupingExtractor):
        pass

    extra_relationships = tuple(
        {
            "relationship_id": f"relationship-{index:02d}",
            "varied_factors": ["scan speed"],
            "outcome": f"porosity measurement variant {index:02d}",
            "source_refs": [
                {"source_kind": "block", "source_ref": f"source-{index:02d}"}
            ],
            "confidence": 0.9,
        }
        for index in range(19)
    )
    skim = _paper_skim(
        document_id="paper-many-pairs",
        relationship_id="relationship-base",
        factors=("scan speed",),
        outcome="porosity measurement variant base",
        extra_relationships=extra_relationships,
    )
    extractor = RecordingExtractor()

    ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=(skim,),
        axis_equivalence_classifier=extractor,
    )

    payload_pairs = [
        pair
        for payload in extractor.canonicalization_payloads
        for pair in payload["axis_pairs"]
    ]
    assert len(extractor.canonicalization_payloads) > 1
    assert all(
        len(payload["axis_pairs"]) <= 16
        for payload in extractor.canonicalization_payloads
    )
    assert len(payload_pairs) == len({pair["pair_id"] for pair in payload_pairs})


def test_variable_alias_canonicalization_does_not_merge_different_outcomes():
    class FuzzyAliasExtractor(_GroupingExtractor):
        def classify(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": pair["axis_type"] == "variable",
                        "same_research_topic": pair["axis_type"] == "variable",
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_skim(
            document_id="paper-temperature-density-1",
            relationship_id="relationship-temperature-density-1",
            factors=("temperature",),
            outcome="relative density",
        ),
        _paper_skim(
            document_id="paper-temperature-density-2",
            relationship_id="relationship-temperature-density-2",
            factors=("temperature",),
            outcome="relative density",
        ),
        _paper_skim(
            document_id="paper-typo-porosity-1",
            relationship_id="relationship-typo-porosity-1",
            factors=("temperatuer",),
            outcome="porosity",
        ),
        _paper_skim(
            document_id="paper-typo-porosity-2",
            relationship_id="relationship-typo-porosity-2",
            factors=("temperatuer",),
            outcome="porosity",
        ),
    )

    service = ObjectiveCandidateService()
    assert _group_relationship_ids(service._build_relationship_groups(skims)) == [
        (
            "relationship-temperature-density-1",
            "relationship-temperature-density-2",
        ),
        (
            "relationship-typo-porosity-1",
            "relationship-typo-porosity-2",
        ),
    ]

    facts = service.discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        axis_equivalence_classifier=FuzzyAliasExtractor(),
    )

    assert {objective.variables for objective in facts.research_objectives} == {
        ("temperature",),
    }
    assert {objective.outcomes for objective in facts.research_objectives} == {
        ("relative density",),
        ("porosity",),
    }
    assert len(facts.study_dispositions) == 4
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}


def test_ranking_prefers_cross_paper_support_then_relationship_count():
    skims = (
        _paper_skim(
            document_id="paper-a-1",
            relationship_id="relationship-a-1",
            factors=("factor a",),
            outcome="outcome a",
            extra_relationships=(
                {
                    "relationship_id": "relationship-a-2",
                    "varied_factors": ["factor a"],
                    "outcome": "outcome a",
                    "source_refs": [
                        {"source_kind": "block", "source_ref": "paper-a-1-extra"}
                    ],
                    "confidence": 0.9,
                },
            ),
        ),
        _paper_skim(
            document_id="paper-a-2",
            relationship_id="relationship-a-3",
            factors=("factor a",),
            outcome="outcome a",
        ),
        _paper_skim(
            document_id="paper-b-1",
            relationship_id="relationship-b-1",
            factors=("factor b",),
            outcome="outcome b",
        ),
        _paper_skim(
            document_id="paper-b-2",
            relationship_id="relationship-b-2",
            factors=("factor b",),
            outcome="outcome b",
        ),
    )
    inventory = ObjectiveCandidateService._relationship_inventory(skims)
    objectives = (
        ResearchObjective.from_mapping(
            {
                "collection_id": "collection-test",
                "objective_id": "objective-fewer-relationships",
                "question": "How does factor b affect outcome b?",
                "variables": ["factor b"],
                "outcomes": ["outcome b"],
                "seed_document_ids": ["paper-b-1", "paper-b-2"],
                "source_relationship_ids": [
                    "relationship-b-1",
                    "relationship-b-2",
                ],
            }
        ),
        ResearchObjective.from_mapping(
            {
                "collection_id": "collection-test",
                "objective_id": "objective-more-relationships",
                "question": "How does factor a affect outcome a?",
                "variables": ["factor a"],
                "outcomes": ["outcome a"],
                "seed_document_ids": ["paper-a-1", "paper-a-2"],
                "source_relationship_ids": [
                    "relationship-a-1",
                    "relationship-a-2",
                    "relationship-a-3",
                ],
            }
        ),
    )

    ranked = ObjectiveCandidateService._rank_objectives(
        objectives,
        relationship_inventory=inventory,
    )

    assert [item.objective_id for item in ranked] == [
        "objective-more-relationships",
        "objective-fewer-relationships",
    ]


def _group_relationship_ids(
    groups: list[list[dict[str, Any]]],
) -> list[tuple[str, ...]]:
    return [
        tuple(str(record["relationship"]["relationship_id"]) for record in group)
        for group in groups
    ]


def _paper_skim(
    *,
    document_id: str,
    relationship_id: str,
    factors: tuple[str, ...] = ("laser power",),
    outcome: str = "relative density",
    material_scope: tuple[str, ...] = ("316L stainless steel",),
    process_context: tuple[str, ...] = ("LPBF",),
    sample_context: tuple[str, ...] = ("vertical coupon",),
    test_context: tuple[str, ...] = ("Archimedes density",),
    fixed_conditions: tuple[str, ...] = ("argon atmosphere",),
    design_type: str = "experimental",
    claim_scope: str = "current_work",
    comparator: str | None = "low versus high setting",
    study_confidence: float = 0.92,
    relationship_confidence: float = 0.9,
    extra_relationships: tuple[dict[str, Any], ...] = (),
) -> PaperSkim:
    return PaperSkim.from_mapping(
        {
            "document_id": document_id,
            "doc_role": "experimental",
            "studies": [
                {
                    "study_id": f"study-{document_id}",
                    "design_type": design_type,
                    "claim_scope": claim_scope,
                    "experiment_label": f"experiment {document_id}",
                    "material_scope": list(material_scope),
                    "process_context": list(process_context),
                    "sample_context": list(sample_context),
                    "test_context": list(test_context),
                    "comparator": comparator,
                    "fixed_conditions": list(fixed_conditions),
                    "relationships": [
                        {
                            "relationship_id": relationship_id,
                            "varied_factors": list(factors),
                            "outcome": outcome,
                            "source_refs": [
                                {
                                    "source_kind": "block",
                                    "source_ref": f"{document_id}-results",
                                }
                            ],
                            "confidence": relationship_confidence,
                        },
                        *extra_relationships,
                    ],
                    "confidence": study_confidence,
                }
            ],
            "evidence_density": "high",
            "confidence": 0.91,
            "warnings": [],
        }
    )
