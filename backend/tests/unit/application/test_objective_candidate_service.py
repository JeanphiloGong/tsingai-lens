from __future__ import annotations

from itertools import permutations
from typing import Any

import pytest

from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredResearchObjectives,
)
from domain.core import PaperSkim, ResearchObjective


class _GroupingExtractor:
    def __init__(self) -> None:
        self.discovery_payloads: list[dict[str, Any]] = []
        self.canonicalization_payloads: list[dict[str, Any]] = []

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        records = payload["paper_relationships"]
        if not records:
            return StructuredResearchObjectives()
        first = records[0]["relationship"]
        factors = first["varied_factors"]
        outcome = first["outcome"]
        auxiliary = "does" if len(factors) == 1 else "do"
        return StructuredResearchObjectives(
            objectives=[
                {
                    "question": (
                        f"How {auxiliary} {' and '.join(factors)} affect {outcome}?"
                    ),
                    "variables": factors,
                    "outcomes": [outcome],
                    "source_relationship_ids": [
                        record["relationship"]["relationship_id"]
                        for record in records
                    ],
                    "confidence": 0.9,
                    "reason": "The backend supplied one compatible relationship group.",
                }
            ]
        )

    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            decisions=[
                {"pair_id": pair["pair_id"], "equivalent": True}
                for pair in payload.get("axis_pairs", ())
            ]
        )


class _EmptyGroupingExtractor(_GroupingExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives()


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
        groups = _group_relationship_ids(
            service._build_relationship_groups(ordering)
        )
        if expected_groups is None:
            expected_groups = groups
        assert groups == expected_groups
        assert all(
            not {"relationship-a", "relationship-c"}.issubset(group)
            for group in groups
        )

    assert expected_groups == [
        ("relationship-a",),
        ("relationship-b",),
        ("relationship-c",),
    ]


def test_missing_context_does_not_attach_to_one_known_context_group():
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

    assert groups == [
        ("relationship-known",),
        ("relationship-missing",),
    ]


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


def test_single_and_joint_factor_relationships_never_share_an_objective_group():
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

    assert groups == [
        ("relationship-joint",),
        ("relationship-single",),
    ]


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
        extractor=_EmptyGroupingExtractor(),
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


def test_different_materials_build_separate_objectives():
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
        extractor=_GroupingExtractor(),
    )

    assert len(facts.research_objectives) == 2
    assert all(
        len(objective.source_relationship_ids) == 1
        for objective in facts.research_objectives
    )
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}


def test_candidate_build_does_not_call_redundant_objective_wording_model():
    class WordingMustNotRunExtractor(_GroupingExtractor):
        def discover_research_objectives(self, payload: dict[str, Any]):
            self.discovery_payloads.append(payload)
            raise AssertionError("objective membership is already backend-owned")

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
        extractor=(extractor := WordingMustNotRunExtractor()),
    )

    assert extractor.discovery_payloads == []
    assert len(facts.research_objectives) == 1
    assert set(facts.research_objectives[0].source_relationship_ids) == {
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
        extractor=_EmptyGroupingExtractor(),
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
        extractor=_GroupingExtractor(),
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
        extractor=extractor,
    )

    assert facts.paper_skims == (skim,)
    assert facts.research_objectives == ()
    assert extractor.discovery_payloads == []
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
        extractor=_EmptyGroupingExtractor(),
    )

    assert facts.research_objectives[0].source_relationship_ids == (
        "relationship-uncertain",
    )
    assert facts.study_dispositions[0].status.value == "promoted"


def test_axis_canonicalization_retains_valid_groups_and_defaults_missing_axes():
    class IncompleteAxisPlanExtractor(_GroupingExtractor):
        def canonicalize_research_objective_axes(
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
        extractor=IncompleteAxisPlanExtractor(),
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


def test_semantic_axis_aliases_are_canonicalized_before_relationship_grouping():
    class SemanticAxisExtractor(_GroupingExtractor):
        def canonicalize_research_objective_axes(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {"pair_id": pair["pair_id"], "equivalent": True}
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
        extractor=extractor,
    )

    assert extractor.discovery_payloads == []
    assert len(facts.research_objectives) == 1
    objective = facts.research_objectives[0]
    assert objective.variables == ("volumetric energy density",)
    assert objective.outcomes == ("fatigue strength",)
    assert set(objective.source_relationship_ids) == {
        "relationship-result-clause",
        "relationship-neutral-axis",
    }
    assert facts.paper_skims == skims
    assert len(facts.study_dispositions) == 2
    assert {item.status.value for item in facts.study_dispositions} == {"promoted"}


def test_material_and_axis_aliases_build_one_cross_paper_objective():
    class MaterialAxisExtractor(_GroupingExtractor):
        def canonicalize_research_objective_axes(
            self,
            payload: dict[str, Any],
        ) -> StructuredAxisCanonicalizationPlan:
            self.canonicalization_payloads.append(payload)
            return StructuredAxisCanonicalizationPlan(
                decisions=[
                    {"pair_id": pair["pair_id"], "equivalent": True}
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
        extractor=extractor,
    )

    assert {
        (pair["axis_type"], pair["left"], pair["right"])
        for pair in extractor.canonicalization_payloads[0]["axis_pairs"]
    } >= {
        ("material", "316L stainless steel", "SS316L"),
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
        extractor=_GroupingExtractor(),
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

    assert _group_relationship_ids(
        service._build_relationship_groups(skims)
    ) == [("relationship-scan", "relationship-scanning")]

    axis_candidates = {
        "material": [],
        "variable": ["scan strategy", "scanning strategy"],
        "outcome": ["UTS", "ultimate tensile strength"],
    }
    axis_pairs = service._build_axis_candidate_pairs(axis_candidates)
    plan = StructuredAxisCanonicalizationPlan(
        decisions=[
            {"pair_id": pair_id, "equivalent": True}
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


def test_axis_pair_selection_is_bounded_and_complete_link_is_order_stable():
    service = ObjectiveCandidateService()
    crowded_candidates = {
        "material": [],
        "variable": [f"scan speed variant {index:03d}" for index in range(40)],
        "outcome": [],
    }

    assert len(service._build_axis_candidate_pairs(crowded_candidates)) <= 96

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
            {"pair_id": pair_id, "equivalent": True}
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


def test_axis_pair_classification_batches_account_for_every_pair_once():
    class RecordingExtractor(_GroupingExtractor):
        pass

    extra_relationships = tuple(
        {
            "relationship_id": f"relationship-{index:02d}",
            "varied_factors": ["scan speed"],
            "outcome": f"porosity variant {index:02d}",
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
        outcome="porosity variant base",
        extra_relationships=extra_relationships,
    )
    extractor = RecordingExtractor()

    ObjectiveCandidateService().discover_candidate_facts(
        "collection-test",
        paper_skims=(skim,),
        extractor=extractor,
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
    assert len(payload_pairs) == len(
        {pair["pair_id"] for pair in payload_pairs}
    )


def test_variable_alias_canonicalization_does_not_merge_different_outcomes():
    class FuzzyAliasExtractor(_EmptyGroupingExtractor):
        def canonicalize_research_objective_axes(
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
        _paper_skim(
            document_id="paper-temperature",
            relationship_id="relationship-temperature",
            factors=("temperature",),
            outcome="relative density",
        ),
        _paper_skim(
            document_id="paper-typo",
            relationship_id="relationship-typo",
            factors=("temperatuer",),
            outcome="porosity",
        ),
    )

    service = ObjectiveCandidateService()
    assert _group_relationship_ids(
        service._build_relationship_groups(skims)
    ) == [
        ("relationship-temperature",),
        ("relationship-typo",),
    ]

    facts = service.discover_candidate_facts(
        "collection-test",
        paper_skims=skims,
        extractor=FuzzyAliasExtractor(),
    )

    assert {objective.variables for objective in facts.research_objectives} == {
        ("temperature",),
    }
    assert {objective.outcomes for objective in facts.research_objectives} == {
        ("relative density",),
        ("porosity",),
    }
    assert len(facts.study_dispositions) == 2
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
        tuple(
            str(record["relationship"]["relationship_id"])
            for record in group
        )
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
                            "confidence": 0.9,
                        },
                        *extra_relationships,
                    ],
                    "confidence": 0.92,
                }
            ],
            "evidence_density": "high",
            "confidence": 0.91,
            "warnings": [],
        }
    )
