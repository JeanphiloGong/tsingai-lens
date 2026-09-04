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
from domain.core import PaperResearchMap, PreparedDocumentInput, ResearchObjective


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
                }
                for pair in payload.get("axis_pairs", ())
            ]
        )


def _document_inputs(
    paper_maps: tuple[PaperResearchMap, ...],
) -> tuple[PreparedDocumentInput, ...]:
    return tuple(
        PreparedDocumentInput(
            document_id=paper_map.document_id,
            preparation_fingerprint=f"fingerprint-{paper_map.document_id}",
        )
        for paper_map in paper_maps
    )


def test_relationship_groups_preserve_complete_study_relationship_records():
    skim = _paper_map(
        document_id="paper-1",
        relationship_id="relationship-density",
        factors=("laser power", "scan speed"),
        outcome="relative density",
        material_scope=("316L stainless steel",),
        process_context=("laser powder bed fusion",),
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
        _paper_map(
            document_id="paper-a",
            relationship_id="relationship-a",
            material_scope=("316L stainless steel",),
        ),
        _paper_map(
            document_id="paper-b",
            relationship_id="relationship-b",
            material_scope=(),
        ),
        _paper_map(
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
        _paper_map(
            document_id="paper-known",
            relationship_id="relationship-known",
            material_scope=("316L stainless steel",),
        ),
        _paper_map(
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
        _paper_map(
            document_id="paper-known",
            relationship_id="relationship-known",
            material_scope=("316L stainless steel",),
        ),
        _paper_map(
            document_id="paper-missing",
            relationship_id="relationship-missing",
            material_scope=(),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
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
        _paper_map(
            document_id="paper-multi-material",
            relationship_id="relationship-known",
            material_scope=("316L stainless steel", "Ti-6Al-4V"),
        ),
        _paper_map(
            document_id="paper-missing",
            relationship_id="relationship-missing",
            material_scope=(),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.material_scope == ()
    assert objective.reason is not None
    assert "No unambiguous shared material scope was available" in objective.reason


def test_missing_confidence_does_not_erase_supported_objective_confidence():
    skims = (
        _paper_map(
            document_id="paper-study-confidence-missing",
            relationship_id="relationship-known",
            study_confidence=0.0,
            relationship_confidence=0.86,
        ),
        _paper_map(
            document_id="paper-relationship-confidence-missing",
            relationship_id="relationship-missing",
            study_confidence=0.82,
            relationship_confidence=0.0,
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    assert facts.research_objectives[0].confidence == pytest.approx(0.82)


def test_all_missing_confidence_remains_zero_with_an_explicit_reason():
    skims = (
        _paper_map(
            document_id="paper-a",
            relationship_id="relationship-a",
            study_confidence=0.0,
            relationship_confidence=0.0,
        ),
        _paper_map(
            document_id="paper-b",
            relationship_id="relationship-b",
            study_confidence=0.0,
            relationship_confidence=0.0,
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.confidence == 0.0
    assert objective.reason is not None
    assert "No source supplied a non-zero confidence" in objective.reason


def test_broad_outcome_group_is_rejected_until_the_outcome_is_specific():
    skims = (
        _paper_map(
            document_id="paper-a",
            relationship_id="relationship-a",
            outcome="mechanical properties",
        ),
        _paper_map(
            document_id="paper-b",
            relationship_id="relationship-b",
            outcome="mechanical properties",
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert facts.research_objectives == ()
    assert {item.status.value for item in facts.study_dispositions} == {"rejected"}
    assert all(
        "requires a specific measurable outcome" in (item.reason or "")
        for item in facts.study_dispositions
    )


def test_microstructure_theme_group_is_rejected_until_an_observation_is_specific():
    skims = (
        _paper_map(
            document_id="paper-a",
            relationship_id="relationship-a",
            factors=("heat treatment",),
            outcome="microstructure",
        ),
        _paper_map(
            document_id="paper-b",
            relationship_id="relationship-b",
            factors=("heat treatment",),
            outcome="microstructure",
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
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
        _paper_map(
            document_id="paper-a",
            relationship_id="relationship-a",
            outcome="densification",
        ),
        _paper_map(
            document_id="paper-b",
            relationship_id="relationship-b",
            outcome="densification",
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
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
        _paper_map(
            document_id="paper-long-form",
            relationship_id="relationship-long-form",
            material_scope=("316L stainless steel",),
        ),
        _paper_map(
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
                    }
                    for pair in payload.get("axis_pairs", ())
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-long-form",
            relationship_id="relationship-long-form",
            material_scope=("316L stainless steel",),
        ),
        _paper_map(
            document_id="paper-reordered",
            relationship_id="relationship-reordered",
            material_scope=("stainless steel 316L",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=RejectingAxisExtractor(),
    )

    assert len(facts.research_objectives) == 1
    assert facts.research_objectives[0].material_scope == ("316L stainless steel",)


def test_tial6v4_notation_keeps_different_intervention_sets_separate():
    skims = (
        _paper_map(
            document_id="paper-iso-notation",
            relationship_id="relationship-iso-notation",
            material_scope=("TiAl6V4",),
            factors=("laser power", "scan rate"),
            outcome="porosity volume fraction",
        ),
        _paper_map(
            document_id="paper-composition-notation",
            relationship_id="relationship-composition-notation",
            material_scope=("Ti-6Al-4V",),
            factors=("laser power", "powder layer thickness"),
            outcome="porosity",
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-ti64-notation",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 2
    assert {
        objective.variables for objective in facts.research_objectives
    } == {
        ("laser power", "scan rate"),
        ("laser power", "powder layer thickness"),
    }


def test_two_relationships_with_missing_material_context_share_one_group():
    skims = (
        _paper_map(
            document_id="paper-a",
            relationship_id="relationship-a",
            material_scope=(),
        ),
        _paper_map(
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
        _paper_map(
            document_id="paper-scan",
            relationship_id="relationship-scan",
            factors=("scan strategy",),
            outcome="UTS",
        ),
        _paper_map(
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
        "design_type": "experimental",
        "claim_scope": "current_work",
    }
    left_context = {**common, changed_field: left_value}
    right_context = {**common, changed_field: right_value}
    skims = (
        _paper_map(
            document_id="paper-left",
            relationship_id="relationship-left",
            **left_context,
        ),
        _paper_map(
            document_id="paper-right",
            relationship_id="relationship-right",
            **right_context,
        ),
    )

    groups = _group_relationship_ids(
        ObjectiveCandidateService()._build_relationship_groups(skims)
    )

    assert groups == [("relationship-left", "relationship-right")]


def test_single_and_joint_factor_relationships_share_a_theme_without_axis_rewriting():
    skims = (
        _paper_map(
            document_id="paper-single",
            relationship_id="relationship-single",
            factors=("laser power",),
        ),
        _paper_map(
            document_id="paper-joint",
            relationship_id="relationship-joint",
            factors=("laser power", "scan speed"),
        ),
    )

    groups = _group_relationship_ids(
        ObjectiveCandidateService()._build_relationship_groups(skims)
    )

    assert groups == [
        ("relationship-joint",),
        ("relationship-single",),
    ]
    assert skims[0].studies[0].relationships[0].varied_factors == ("laser power",)
    assert skims[1].studies[0].relationships[0].varied_factors == (
        "laser power",
        "scan speed",
    )


def test_distinct_thermal_processing_interventions_create_distinct_objectives():
    class DistinctAxisClassifier(_GroupingExtractor):
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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-annealing",
            relationship_id="relationship-annealing",
            factors=("annealing temperature",),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_map(
            document_id="paper-solution-aging",
            relationship_id="relationship-solution-aging",
            factors=("solution temperature", "aging temperature"),
            outcome="elongation",
            material_scope=("Ti6Al4V",),
        ),
        _paper_map(
            document_id="paper-hip",
            relationship_id="relationship-hip",
            factors=("HIP temperature",),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_map(
            document_id="paper-build-preheating",
            relationship_id="relationship-build-preheating",
            factors=("base plate preheating temperature",),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-ti64-thermal-processing",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=DistinctAxisClassifier(),
    )

    assert len(facts.research_objectives) == 4
    assert {
        objective.variables for objective in facts.research_objectives
    } == {
        ("annealing temperature",),
        ("solution temperature", "aging temperature"),
        ("HIP temperature",),
        ("base plate preheating temperature",),
    }
    dispositions = {
        item.relationship_id: item for item in facts.study_dispositions
    }
    assert {
        item.status.value for item in dispositions.values()
    } == {"promoted"}
    assert skims[1].studies[0].relationships[0].varied_factors == (
        "solution temperature",
        "aging temperature",
    )


def test_shared_topic_preserves_different_joint_interventions():
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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
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
        _paper_map(
            document_id="paper-hip-results",
            relationship_id="relationship-hip-results",
            factors=("HIP cooling rate", "post-processing route"),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-ti64-cooling",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=CoolingTopicClassifier(),
    )

    assert len(facts.research_objectives) == 2
    assert {
        objective.variables for objective in facts.research_objectives
    } == {
        ("cooling rate after HIP", "HIP temperature", "parent beta grain size"),
        ("HIP cooling rate", "post-processing route"),
    }
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}
    assert skims[0].studies[0].relationships[0].varied_factors == (
        "cooling rate after HIP",
        "HIP temperature",
        "parent beta grain size",
    )


def test_hip_relations_keep_each_intervention_as_a_candidate():
    class HipTopicClassifier(_GroupingExtractor):
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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    paper_factors = (
        "HIP cooling rate",
        "HIP pressure",
        "HIP temperature",
        "HIP hold time",
        "HIP heating rate",
        "HIP post-processing condition",
    )
    skims = tuple(
        _paper_map(
            document_id=f"paper-hip-{position}",
            relationship_id=f"relationship-hip-{position}",
            factors=(factor,),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        )
        for position, factor in enumerate(paper_factors, start=1)
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-ti64-hip-topic",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=HipTopicClassifier(),
    )

    assert len(facts.research_objectives) == len(paper_factors)
    assert {
        objective.variables for objective in facts.research_objectives
    } == {(factor,) for factor in paper_factors}
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}
    assert {
        skim.studies[0].relationships[0].varied_factors[0] for skim in skims
    } == set(paper_factors)


def test_laser_exposure_theme_does_not_rewrite_precise_axes():
    class LaserExposureTopicClassifier(_GroupingExtractor):
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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-fixed-power",
            relationship_id="relationship-fixed-power",
            factors=("laser power",),
            outcome="relative density",
        ),
        _paper_map(
            document_id="paper-ved",
            relationship_id="relationship-ved",
            factors=("volumetric energy density",),
            outcome="relative density",
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-316l-topic-only",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=LaserExposureTopicClassifier(),
    )

    assert len(facts.research_objectives) == 2
    assert {
        objective.variables for objective in facts.research_objectives
    } == {
        ("laser power",),
        ("volumetric energy density",),
    }
    assert all(
        "direct comparability remains a later evidence decision" in str(objective.reason)
        for objective in facts.research_objectives
    )
    assert skims[0].studies[0].relationships[0].varied_factors == ("laser power",)
    assert skims[1].studies[0].relationships[0].varied_factors == (
        "volumetric energy density",
    )


def test_cross_paper_theme_keeps_joint_and_isolated_interventions_distinct():
    class LaserFactorClassifier(_GroupingExtractor):
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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-joint",
            relationship_id="relationship-joint",
            factors=("laser power", "scan speed"),
            outcome="relative density",
        ),
        _paper_map(
            document_id="paper-isolated",
            relationship_id="relationship-isolated",
            factors=("laser power",),
            outcome="relative density",
        ),
        _paper_map(
            document_id="paper-cited",
            relationship_id="relationship-cited",
            factors=("laser power",),
            outcome="relative density",
            claim_scope="background",
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-316l-joint-factor",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=LaserFactorClassifier(),
    )

    assert len(facts.research_objectives) == 2
    assert {
        objective.variables for objective in facts.research_objectives
    } == {
        ("laser power", "scan speed"),
        ("laser power",),
    }
    dispositions = {
        item.relationship_id: item for item in facts.study_dispositions
    }
    assert dispositions["relationship-cited"].status.value == "rejected"
    assert "claim_scope=background" in str(
        dispositions["relationship-cited"].reason
    )
    assert skims[0].studies[0].relationships[0].varied_factors == (
        "laser power",
        "scan speed",
    )
    assert skims[1].studies[0].relationships[0].varied_factors == ("laser power",)


def test_discovery_trace_accounts_for_relationships_signals_and_source_coverage(
    caplog: pytest.LogCaptureFixture,
):
    current_work_skim = _paper_map(
        document_id="paper-accounting",
        relationship_id="relationship-promoted",
        factors=("laser power",),
        outcome="relative density",
    )
    background_study = _paper_map(
        document_id="paper-accounting",
        relationship_id="relationship-rejected",
        factors=("scan speed",),
        outcome="surface roughness",
        claim_scope="background",
    ).studies[0].to_record()
    skim = PaperResearchMap.from_mapping(
        {
            **current_work_skim.to_record(),
            "studies": [
                current_work_skim.studies[0].to_record(),
                {
                    **background_study,
                    "study_id": "study-paper-accounting-background",
                },
            ],
            "unresolved_signals": [
                {
                    "signal_id": "signal-unresolved",
                    "signal_type": "outcome",
                    "label": "melt-pool morphology",
                    "design_type": "experimental",
                    "claim_scope": "current_work",
                    "source_refs": [
                        {
                            "source_kind": "figure",
                            "source_ref": "figure-unresolved",
                        }
                    ],
                    "confidence": 0.72,
                    "reason": "No defensible varied factor was extracted.",
                }
            ],
            "source_unit_coverage": [
                {
                    "source_unit_id": "unit-relationship",
                    "window_id": "window-relationship",
                    "source_kind": "block",
                    "source_ref": "block-relationship",
                    "status": "relationship_emitted",
                },
                {
                    "source_unit_id": "unit-unresolved",
                    "window_id": "window-unresolved",
                    "source_kind": "figure",
                    "source_ref": "figure-unresolved",
                    "status": "unresolved_signal_emitted",
                },
                {
                    "source_unit_id": "unit-no-signal",
                    "window_id": "window-no-signal",
                    "source_kind": "block",
                    "source_ref": "block-no-signal",
                    "status": "no_study_signal",
                    "reason": "The Source unit contains no study signal.",
                },
                {
                    "source_unit_id": "unit-failed",
                    "window_id": "window-failed",
                    "source_kind": "table",
                    "source_ref": "table-failed",
                    "status": "extraction_failed",
                    "reason": "The extraction response was invalid.",
                },
            ],
        }
    )
    caplog.set_level(
        "INFO",
        logger="application.core.objectives.objective_candidate_service",
    )

    ObjectiveCandidateService().discover_candidate_facts(
        "collection-accounting",
        paper_maps=(skim,),
        document_inputs=_document_inputs((skim,)),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    trace = next(
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("Research objective discovery finished")
    )
    assert "relationship_count=2" in trace
    assert "promoted_relationship_count=1" in trace
    assert "rejected_relationship_count=1" in trace
    assert "pending_relationship_count=0" in trace
    assert "relationship_accounting_complete=True" in trace
    assert "unresolved_signal_count=1" in trace
    assert "relationship_emitted_count=1" in trace
    assert "unresolved_signal_emitted_count=1" in trace
    assert "no_study_signal_count=1" in trace
    assert "extraction_failed_count=1" in trace
    assert "coverage_complete=False" in trace
    assert "laser power" not in trace
    assert "melt-pool morphology" not in trace


def test_shared_parent_theme_keeps_each_papers_complete_intervention():
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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-a",
            relationship_id="relationship-a",
            factors=("cooling rate after HIP", "HIP temperature"),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_map(
            document_id="paper-b",
            relationship_id="relationship-b",
            factors=("HIP cooling rate", "post-processing route"),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_map(
            document_id="paper-c",
            relationship_id="relationship-c",
            factors=("heat treatment temperature", "scan strategy"),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-local-topic-bridges",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=LocalTopicClassifier(),
    )

    assert len(facts.research_objectives) == 3
    assert {
        objective.variables for objective in facts.research_objectives
    } == {
        ("cooling rate after HIP", "HIP temperature"),
        ("HIP cooling rate", "post-processing route"),
        ("heat treatment temperature", "scan strategy"),
    }
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}
    assert skims[2].studies[0].relationships[0].varied_factors == (
        "heat treatment temperature",
        "scan strategy",
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
                if pair["axis_type"] == "variable":
                    assert pair["left_observations"]
                    assert pair["right_observations"]
                    for side in ("left", "right"):
                        for observation in pair[f"{side}_observations"]:
                            assert pair[side] in observation["varied_factors"]
                            assert len(observation["varied_factors"]) <= 6
                            assert len(observation["process_context"]) <= 2
                            assert all(
                                len(value) <= 120
                                for values in observation.values()
                                for value in values
                            )
                decisions.append(
                    {
                        "pair_id": pair["pair_id"],
                        "equivalent": False,
                    }
                )
            return StructuredAxisCanonicalizationPlan(decisions=decisions)

    skims = (
        _paper_map(
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
        ),
        _paper_map(
            document_id="paper-orientation",
            relationship_id="relationship-orientation",
            factors=("sample orientation",),
            outcome="ultimate tensile strength",
            process_context=("laser powder bed fusion",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-orientation",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=ContextAwareClassifier(),
    )

    assert len(facts.research_objectives) == 2
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}
    assert skims[0].studies[0].relationships[0].varied_factors == (
        "build orientation",
        "laser speed",
        "laser power",
        "gauge cross section",
        "layer thickness",
        "hatch spacing",
        "scan rotation",
    )


def test_topic_only_pairs_are_classified_once_without_affecting_objectives():
    class TopicClassifier(_GroupingExtractor):
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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    classifier = TopicClassifier()
    skims = (
        _paper_map(
            document_id="paper-build",
            relationship_id="relationship-build",
            factors=("build orientation",),
            outcome="ultimate tensile strength",
        ),
        _paper_map(
            document_id="paper-laser",
            relationship_id="relationship-laser",
            factors=("tensile orientation",),
            outcome="ultimate tensile strength",
        ),
        _paper_map(
            document_id="paper-sample",
            relationship_id="relationship-sample",
            factors=("sample orientation",),
            outcome="ultimate tensile strength",
        ),
    )
    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-confirm-topic",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=classifier,
    )

    assert len(classifier.canonicalization_payloads) == 1
    assert len(classifier.canonicalization_payloads[0]["axis_pairs"]) == 3
    assert "decision_stage" not in classifier.canonicalization_payloads[0]
    assert len(facts.research_objectives) == 3
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}


def test_different_measured_outcomes_never_share_an_objective_group():
    skims = (
        _paper_map(
            document_id="paper-porosity",
            relationship_id="relationship-porosity",
            outcome="porosity",
        ),
        _paper_map(
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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-microstructure",
            relationship_id="relationship-microstructure",
            factors=("annealing temperature",),
            outcome="microstructure",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_map(
            document_id="paper-strength",
            relationship_id="relationship-strength",
            factors=("annealing temperature",),
            outcome="yield strength",
            material_scope=("Ti6Al4V",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-focused-outcome",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=RelatedOutcomeClassifier(),
    )

    assert len(facts.research_objectives) == 1
    assert facts.research_objectives[0].variables == ("annealing temperature",)
    assert facts.research_objectives[0].outcomes == ("yield strength",)
    dispositions = {
        item.relationship_id: item for item in facts.study_dispositions
    }
    assert dispositions["relationship-microstructure"].status.value == "rejected"
    assert dispositions["relationship-strength"].status.value == "promoted"


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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-alpha-prime",
            relationship_id="relationship-alpha-prime",
            factors=("heat treatment condition",),
            outcome="alpha-prime fraction",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_map(
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
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
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


def test_property_aliases_are_not_repeated_in_the_objective_outcomes():
    class RejectModelAliases(_GroupingExtractor):
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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-ductility",
            relationship_id="relationship-ductility",
            factors=("heat treatment temperature",),
            outcome="ductility",
            material_scope=("Ti-6Al-4V",),
        ),
        _paper_map(
            document_id="paper-elongation",
            relationship_id="relationship-elongation",
            factors=("heat treatment temperature",),
            outcome="elongation",
            material_scope=("Ti-6Al-4V",),
        ),
    )
    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-ductility-alias",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=RejectModelAliases(),
    )

    assert len(facts.research_objectives) == 1
    assert facts.research_objectives[0].outcomes == ("elongation",)
    assert facts.research_objectives[0].question == (
        "How does heat treatment temperature affect elongation?"
    )


def test_joint_factors_are_indivisible_and_each_outcome_is_accounted_separately():
    skim = _paper_map(
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
        paper_maps=(skim,),
        document_inputs=_document_inputs((skim,)),
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
        _paper_map(
            document_id="paper-steel",
            relationship_id="relationship-steel",
            material_scope=("316L stainless steel",),
        ),
        _paper_map(
            document_id="paper-ti",
            relationship_id="relationship-ti",
            material_scope=("Ti-6Al-4V",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 2
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}


def test_candidate_build_derives_objective_identity_and_lineage_from_relationships():
    skims = tuple(
        _paper_map(
            document_id=f"paper-{index}",
            relationship_id=f"relationship-{index}",
        )
        for index in range(3)
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
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
        _paper_map(
            document_id="paper-a",
            relationship_id="relationship-a",
            process_context=("context alpha",),
        ),
        _paper_map(
            document_id="paper-b",
            relationship_id="relationship-b",
            process_context=("context beta",),
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert "context alpha" not in objective.constraints
    assert "context beta" not in objective.constraints
    assert skims[0].studies[0].process_context == ("context alpha",)
    assert skims[1].studies[0].process_context == ("context beta",)
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
        _paper_map(
            document_id=f"paper-{index}",
            relationship_id=f"relationship-{index}",
        )
        for index in range(3)
    )
    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
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
    skim = _paper_map(
        document_id="paper-review",
        relationship_id="relationship-review",
        claim_scope=claim_scope,
    )
    extractor = _GroupingExtractor()

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=(skim,),
        document_inputs=_document_inputs((skim,)),
        axis_equivalence_classifier=extractor,
    )

    assert facts.document_inputs == _document_inputs((skim,))
    assert facts.research_objectives == ()
    assert len(facts.study_dispositions) == 1
    disposition = facts.study_dispositions[0]
    assert disposition.relationship_id == "relationship-review"
    assert disposition.status.value == "rejected"
    assert claim_scope in str(disposition.reason)


def test_uncertain_claim_scope_cannot_seed_a_precise_candidate():
    skim = _paper_map(
        document_id="paper-uncertain",
        relationship_id="relationship-uncertain",
        claim_scope="uncertain",
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=(skim,),
        document_inputs=_document_inputs((skim,)),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert facts.research_objectives == ()
    assert facts.study_dispositions[0].status.value == "rejected"
    assert "claim_scope=uncertain" in str(facts.study_dispositions[0].reason)


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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-1",
            relationship_id="relationship-1",
            outcome="maximum defect diameter",
        ),
        _paper_map(
            document_id="paper-2",
            relationship_id="relationship-2",
            outcome="max defect diameter",
        ),
        _paper_map(
            document_id="paper-3",
            relationship_id="relationship-3",
            outcome="max defect length",
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=IncompleteAxisPlanExtractor(),
    )

    assert {objective.outcomes for objective in facts.research_objectives} == {
        ("max defect diameter",),
        ("max defect length",),
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
    assert length_disposition.status.value == "promoted"


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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-result-clause",
            relationship_id="relationship-result-clause",
            factors=("VED",),
            outcome="fatigue strength decreases with lower VED",
        ),
        _paper_map(
            document_id="paper-neutral-axis",
            relationship_id="relationship-neutral-axis",
            factors=("volumetric energy density",),
            outcome="fatigue strength",
        ),
    )
    extractor = SemanticAxisExtractor()

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
        axis_equivalence_classifier=extractor,
    )

    assert len(facts.research_objectives) == 2
    assert facts.document_inputs == _document_inputs(skims)
    assert len(facts.study_dispositions) == 2
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}


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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-long-form",
            relationship_id="relationship-long-form",
            factors=("laser power", "scan speed"),
            outcome="porosity",
            material_scope=("316L stainless steel",),
        ),
        _paper_map(
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
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
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
    assert facts.document_inputs == _document_inputs(skims)
    assert skims[1].studies[0].material_scope == ("SS316L",)


def test_objective_constraints_omit_the_relationship_axes():
    skim = _paper_map(
        document_id="paper-heat-treatment",
        relationship_id="relationship-heat-treatment",
        factors=("heat treatment",),
        outcome="grain morphology",
        process_context=("LPBF", "heat treatment"),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=(skim,),
        document_inputs=_document_inputs((skim,)),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.constraints == (
        "LPBF",
        "experimental",
        "current_work",
    )
    assert facts.study_dispositions[0].status.value == "promoted"


def test_verified_aliases_are_consistent_through_context_and_canonicalization():
    skims = (
        _paper_map(
            document_id="paper-scan",
            relationship_id="relationship-scan",
            factors=("scan strategy",),
            outcome="UTS",
        ),
        _paper_map(
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
            _paper_map(
                document_id="paper-a",
                relationship_id="relationship-a",
                outcome="mechanical properties",
            ),
            _paper_map(
                document_id="paper-b",
                relationship_id="relationship-b",
                outcome="yield strength",
            ),
            _paper_map(
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
        _paper_map(
            document_id="paper-heat",
            relationship_id="relationship-heat",
            factors=("heat treatment temperature",),
            outcome="elongation",
            process_context=("LPBF", "post-build heat treatment"),
        ),
        _paper_map(
            document_id="paper-anneal",
            relationship_id="relationship-anneal",
            factors=("annealing duration",),
            outcome="elongation",
            process_context=("SLM", "post-build annealing"),
        ),
        _paper_map(
            document_id="paper-preheat",
            relationship_id="relationship-preheat",
            factors=("base plate preheating temperature",),
            outcome="elongation",
            process_context=("LPBF", "in-process preheating"),
        ),
        _paper_map(
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
        _paper_map(
            document_id="paper-strength",
            relationship_id="relationship-strength",
            outcome="yield strength",
        ),
        _paper_map(
            document_id="paper-ductility",
            relationship_id="relationship-ductility",
            outcome="elongation",
        ),
        _paper_map(
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
    skim = _paper_map(
        document_id="paper-many-pairs",
        relationship_id="relationship-base",
        factors=("scan speed",),
        outcome="porosity measurement variant base",
        extra_relationships=extra_relationships,
    )
    extractor = RecordingExtractor()

    ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_maps=(skim,),
        document_inputs=_document_inputs((skim,)),
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
                    }
                    for pair in payload["axis_pairs"]
                ]
            )

    skims = (
        _paper_map(
            document_id="paper-temperature-density-1",
            relationship_id="relationship-temperature-density-1",
            factors=("temperature",),
            outcome="relative density",
        ),
        _paper_map(
            document_id="paper-temperature-density-2",
            relationship_id="relationship-temperature-density-2",
            factors=("temperature",),
            outcome="relative density",
        ),
        _paper_map(
            document_id="paper-typo-porosity-1",
            relationship_id="relationship-typo-porosity-1",
            factors=("temperatuer",),
            outcome="porosity",
        ),
        _paper_map(
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
        paper_maps=skims,
        document_inputs=_document_inputs(skims),
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
        _paper_map(
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
        _paper_map(
            document_id="paper-a-2",
            relationship_id="relationship-a-3",
            factors=("factor a",),
            outcome="outcome a",
        ),
        _paper_map(
            document_id="paper-b-1",
            relationship_id="relationship-b-1",
            factors=("factor b",),
            outcome="outcome b",
        ),
        _paper_map(
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


def test_ranking_prefers_structured_result_sources_before_relationship_count():
    skims = (
        _paper_map(
            document_id="paper-table-a",
            relationship_id="relationship-table-a",
            source_kind="table",
        ),
        _paper_map(
            document_id="paper-table-b",
            relationship_id="relationship-table-b",
            source_kind="table",
        ),
        _paper_map(
            document_id="paper-block-a",
            relationship_id="relationship-block-a",
        ),
        _paper_map(
            document_id="paper-block-b",
            relationship_id="relationship-block-b",
        ),
    )
    inventory = ObjectiveCandidateService._relationship_inventory(skims)
    objectives = (
        ResearchObjective.from_mapping(
            {
                "collection_id": "collection-test",
                "objective_id": "objective-block",
                "question": "How does laser power affect relative density?",
                "variables": ["laser power"],
                "outcomes": ["relative density"],
                "seed_document_ids": ["paper-block-a", "paper-block-b"],
                "source_relationship_ids": [
                    "relationship-block-a",
                    "relationship-block-b",
                ],
            }
        ),
        ResearchObjective.from_mapping(
            {
                "collection_id": "collection-test",
                "objective_id": "objective-table",
                "question": "How does laser power affect relative density?",
                "variables": ["laser power"],
                "outcomes": ["relative density"],
                "seed_document_ids": ["paper-table-a", "paper-table-b"],
                "source_relationship_ids": [
                    "relationship-table-a",
                    "relationship-table-b",
                ],
            }
        ),
    )

    ranked = ObjectiveCandidateService._rank_objectives(
        objectives,
        relationship_inventory=inventory,
    )

    assert [item.objective_id for item in ranked] == [
        "objective-table",
        "objective-block",
    ]


def test_ranking_prefers_structured_results_from_independent_papers():
    concentrated_extra_relationships = tuple(
        {
            "relationship_id": f"relationship-concentrated-table-{index}",
            "varied_factors": ["laser power"],
            "outcome": "relative density",
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": f"paper-concentrated-a-table-{index}",
                }
            ],
            "confidence": 0.9,
        }
        for index in (1, 2)
    )
    skims = (
        _paper_map(
            document_id="paper-distributed-a",
            relationship_id="relationship-distributed-a",
            source_kind="table",
        ),
        _paper_map(
            document_id="paper-distributed-b",
            relationship_id="relationship-distributed-b",
            source_kind="table",
        ),
        _paper_map(
            document_id="paper-concentrated-a",
            relationship_id="relationship-concentrated-a",
            extra_relationships=concentrated_extra_relationships,
        ),
        _paper_map(
            document_id="paper-concentrated-b",
            relationship_id="relationship-concentrated-b",
        ),
    )
    inventory = ObjectiveCandidateService._relationship_inventory(skims)
    objectives = (
        ResearchObjective.from_mapping(
            {
                "collection_id": "collection-test",
                "objective_id": "objective-concentrated",
                "question": "How does laser power affect relative density?",
                "variables": ["laser power"],
                "outcomes": ["relative density"],
                "seed_document_ids": [
                    "paper-concentrated-a",
                    "paper-concentrated-b",
                ],
                "source_relationship_ids": [
                    "relationship-concentrated-a",
                    "relationship-concentrated-b",
                    "relationship-concentrated-table-1",
                    "relationship-concentrated-table-2",
                ],
            }
        ),
        ResearchObjective.from_mapping(
            {
                "collection_id": "collection-test",
                "objective_id": "objective-distributed",
                "question": "How does laser power affect relative density?",
                "variables": ["laser power"],
                "outcomes": ["relative density"],
                "seed_document_ids": [
                    "paper-distributed-a",
                    "paper-distributed-b",
                ],
                "source_relationship_ids": [
                    "relationship-distributed-a",
                    "relationship-distributed-b",
                ],
            }
        ),
    )

    ranked = ObjectiveCandidateService._rank_objectives(
        objectives,
        relationship_inventory=inventory,
    )

    assert [item.objective_id for item in ranked] == [
        "objective-distributed",
        "objective-concentrated",
    ]


def test_repeated_paper_relationships_share_one_candidate_lineage():
    skim = _paper_map(
        document_id="paper-repeated",
        relationship_id="relationship-repeated-a",
        factors=("volumetric energy density",),
        outcome="fatigue limit",
        source_kind="block",
        extra_relationships=(
            {
                "relationship_id": "relationship-repeated-b",
                "varied_factors": ["volumetric energy density"],
                "outcome": "fatigue limit",
                "source_refs": [
                    {"source_kind": "table", "source_ref": "paper-repeated-table"}
                ],
                "confidence": 0.8,
            },
        ),
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-repeated",
        paper_maps=(skim,),
        document_inputs=_document_inputs((skim,)),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 1
    assert set(facts.research_objectives[0].source_relationship_ids) == {
        "relationship-repeated-a",
        "relationship-repeated-b",
    }


def test_relationship_with_same_variable_and_outcome_is_not_a_candidate():
    skim = _paper_map(
        document_id="paper-self-relation",
        relationship_id="relationship-self-relation",
        factors=("porosity",),
        outcome="porosity",
    )

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-self-relation",
        paper_maps=(skim,),
        document_inputs=_document_inputs((skim,)),
        axis_equivalence_classifier=_GroupingExtractor(),
    )

    assert facts.research_objectives == ()
    assert facts.study_dispositions[0].status.value == "rejected"
    assert "same variable" in (facts.study_dispositions[0].reason or "")


def test_candidate_review_set_is_bounded_without_losing_relationship_accounting():
    class DistinctAxisExtractor(_GroupingExtractor):
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
                    }
                    for pair in payload.get("axis_pairs", ())
                ]
            )

    paper_maps = []
    for document_number in range(1, 6):
        extra_relationships = tuple(
            {
                "relationship_id": f"relationship-{document_number}-{index}",
                "varied_factors": [f"factor {document_number}-{index}"],
                "outcome": f"outcome {document_number}-{index}",
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": f"paper-{document_number}-table-{index}",
                    }
                ],
                "confidence": 0.8,
            }
            for index in range(1, 4)
        )
        paper_maps.append(
            _paper_map(
                document_id=f"paper-{document_number}",
                relationship_id=f"relationship-{document_number}-0",
                factors=(f"factor {document_number}-0",),
                outcome=f"outcome {document_number}-0",
                extra_relationships=extra_relationships,
            )
        )
    maps = tuple(paper_maps)

    facts = ObjectiveCandidateService().discover_candidate_facts(
        "collection-bounded-review",
        paper_maps=maps,
        document_inputs=_document_inputs(maps),
        axis_equivalence_classifier=DistinctAxisExtractor(),
    )

    assert len(facts.research_objectives) == 15
    assert {
        document_id
        for objective in facts.research_objectives
        for document_id in objective.seed_document_ids
    } == {f"paper-{number}" for number in range(1, 6)}
    assert len(facts.study_dispositions) == 20
    dropped = [
        item
        for item in facts.study_dispositions
        if item.status.value == "rejected"
        and "bounded candidate review set" in (item.reason or "")
    ]
    assert len(dropped) == 5


def _group_relationship_ids(
    groups: list[list[dict[str, Any]]],
) -> list[tuple[str, ...]]:
    return [
        tuple(str(record["relationship"]["relationship_id"]) for record in group)
        for group in groups
    ]


def _paper_map(
    *,
    document_id: str,
    relationship_id: str,
    factors: tuple[str, ...] = ("laser power",),
    outcome: str = "relative density",
    source_kind: str = "block",
    material_scope: tuple[str, ...] = ("316L stainless steel",),
    process_context: tuple[str, ...] = ("LPBF",),
    design_type: str = "experimental",
    claim_scope: str = "current_work",
    study_confidence: float = 0.92,
    relationship_confidence: float = 0.9,
    extra_relationships: tuple[dict[str, Any], ...] = (),
) -> PaperResearchMap:
    return PaperResearchMap.from_mapping(
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
                    "relationships": [
                        {
                            "relationship_id": relationship_id,
                            "varied_factors": list(factors),
                            "outcome": outcome,
                            "source_refs": [
                                {
                                    "source_kind": source_kind,
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
