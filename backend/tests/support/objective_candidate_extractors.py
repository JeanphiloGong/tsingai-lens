from __future__ import annotations

from typing import Any

from application.core.objectives.schemas import (
    StructuredAxisCanonicalizationGroup,
    StructuredAxisCanonicalizationPlan,
    StructuredEvidenceExtraction,
    StructuredEvidenceExtractions,
    StructuredObjectiveMergeGroup,
    StructuredObjectiveMergePlan,
    StructuredPaperSkim,
    StructuredResearchObjective,
    StructuredResearchObjectives,
)
from tests.support.objective_extractor import FakeObjectiveExtractor


class BroadObjectiveExtractor(FakeObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            candidate_processes=["Selective Laser Melting"],
            candidate_properties=[
                "mechanical properties",
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "microhardness",
            ],
            changed_variables=[
                "energy density",
                "scanning strategy",
                "scanning speed",
            ],
            possible_objectives=[
                "How do energy density, scanning strategy, and scanning speed "
                "affect mechanical properties?"
            ],
            evidence_density="high",
            confidence=0.91,
            warnings=[],
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How do energy density, scanning strategy, and scanning speed "
                        "affect mechanical properties?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=[
                        "energy density",
                        "scanning strategy",
                        "scanning speed",
                    ],
                    outcomes=["mechanical properties"],
                    constraints=["Selective Laser Melting"],
                    requested_comparator=None,
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.88,
                    reason="paper skim points to mechanical-property comparison",
                )
            ]
        )


class DuplicateMechanicalObjectiveExtractor(BroadObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            candidate_processes=["Selective Laser Melting"],
            possible_objectives=[
                "How do energy density, scanning strategy, and scanning speed "
                "affect densification and microstructure?",
                "What are the effects of energy density and scanning speed on "
                "yield strength, ultimate tensile strength, elongation, and "
                "microhardness?",
                "How does scanning strategy influence yield strength and "
                "microhardness?",
            ],
            evidence_density="high",
            confidence=0.91,
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How do energy density, scanning strategy, and scanning "
                        "speed affect densification and microstructure?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=[
                        "energy density",
                        "scanning strategy",
                        "scanning speed",
                    ],
                    outcomes=["densification", "microstructure"],
                    constraints=["Selective Laser Melting"],
                    requested_comparator=(
                        "Compare the effects of energy density, scanning strategy, "
                        "and scanning speed on densification and microstructure."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="processing parameters affect density and structure",
                ),
                StructuredResearchObjective(
                    question=(
                        "What are the effects of energy density and "
                        "scanning speed on yield strength, ultimate tensile "
                        "strength, elongation, and microhardness?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=[
                        "energy density",
                        "scanning speed",
                    ],
                    outcomes=[
                        "yield strength",
                        "ultimate tensile strength",
                        "elongation",
                        "microhardness",
                    ],
                    constraints=["Selective Laser Melting"],
                    requested_comparator=(
                        "Analyze how changes in energy density and scanning speed "
                        "influence mechanical properties."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="mechanical properties are reported together",
                ),
                StructuredResearchObjective(
                    question=(
                        "How does scanning strategy influence yield strength and "
                        "microhardness?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=["scanning strategy"],
                    outcomes=["yield strength", "microhardness"],
                    constraints=["Selective Laser Melting"],
                    requested_comparator=(
                        "Evaluate scanning strategy effects on yield strength "
                        "and microhardness."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="mechanical properties overlap with the prior objective",
                ),
            ]
        )

    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        candidates = payload["candidate_objectives"]
        structure_candidates = [
            candidate
            for candidate in candidates
            if "densification" in candidate["outcomes"]
        ]
        mechanical_candidates = [
            candidate
            for candidate in candidates
            if "yield strength" in candidate["outcomes"]
        ]
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in structure_candidates
                    ],
                    question=structure_candidates[0]["question"],
                    material_scope=structure_candidates[0]["material_scope"],
                    variables=structure_candidates[0]["variables"],
                    outcomes=structure_candidates[0]["outcomes"],
                    requested_comparator=structure_candidates[0]["requested_comparator"],
                    confidence=0.9,
                    reason="kept structure objective separate",
                ),
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in mechanical_candidates
                    ],
                    question=(
                        "How do energy density, scanning speed, and scanning "
                        "strategy affect yield strength, ultimate tensile strength, "
                        "elongation, and microhardness?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=merge_candidate_values(
                        mechanical_candidates,
                        "variables",
                    ),
                    outcomes=merge_candidate_values(
                        mechanical_candidates,
                        "outcomes",
                    ),
                    requested_comparator=(
                        "Compare the combined effects of energy density, scanning "
                        "speed, and scanning strategy on mechanical properties."
                    ),
                    confidence=0.9,
                    reason="merged overlapping mechanical objectives",
                ),
            ]
        )


class DroppedObjectiveMergeExtractor(DuplicateMechanicalObjectiveExtractor):
    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        candidate = payload["candidate_objectives"][0]
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[candidate["objective_id"]],
                    question=candidate["question"],
                    material_scope=candidate["material_scope"],
                    variables=candidate["variables"],
                    outcomes=candidate["outcomes"],
                    requested_comparator=candidate["requested_comparator"],
                    confidence=candidate["confidence"],
                    reason="invalid plan drops other candidates",
                )
            ]
        )


class CanonicalizingAxisExtractor(DuplicateMechanicalObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            candidate_processes=["Selective Laser Melting", "scanning strategy"],
            candidate_properties=[
                "mechanical properties",
                "yield strength",
                "ultimate tensile strength",
                "elongation",
                "microhardness",
                "densification",
                "microstructure",
            ],
            changed_variables=[
                "energy density",
                "scan strategy",
                "scanning speed",
            ],
            possible_objectives=[
                "How do energy density, scanning strategy, and scanning speed "
                "affect densification and microstructure?",
                "What are the effects of energy density and scanning speed on "
                "yield strength, ultimate tensile strength, elongation, and "
                "microhardness?",
                "How does scanning strategy influence yield strength and "
                "microhardness?",
            ],
            evidence_density="high",
            confidence=0.91,
            warnings=[],
        )

    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            axis_groups=[
                StructuredAxisCanonicalizationGroup(
                    axis_type="material",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["material"]
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="variable",
                    canonical="scanning strategy",
                    aliases=["scanning strategy", "scan strategy"],
                    confidence=0.95,
                    reason="same process variable phrased two ways",
                ),
                *[
                    StructuredAxisCanonicalizationGroup(
                        axis_type="variable",
                        canonical=value,
                        aliases=[value],
                        confidence=1.0,
                        reason="kept separate",
                    )
                    for value in payload["axis_candidates"]["variable"]
                    if value not in {"scanning strategy", "scan strategy"}
                ],
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="outcome",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["outcome"]
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="constraint",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["constraint"]
            ]
        )


class InvalidAxisCanonicalizationExtractor(CanonicalizingAxisExtractor):
    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            axis_groups=[
                StructuredAxisCanonicalizationGroup(
                    axis_type="variable",
                    canonical="scanning strategy",
                    aliases=["scanning strategy", "scan strategy"],
                    confidence=0.95,
                    reason="invalid plan drops material and property axes",
                )
            ]
        )


class OverbroadAxisCanonicalizationExtractor(CanonicalizingAxisExtractor):
    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            axis_groups=[
                StructuredAxisCanonicalizationGroup(
                    axis_type="material",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["material"]
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="variable",
                    canonical="Selective Laser Melting",
                    aliases=payload["axis_candidates"]["variable"],
                    confidence=0.9,
                    reason="invalidly collapses distinct process axes",
                ),
            ]
            + [
                StructuredAxisCanonicalizationGroup(
                    axis_type="outcome",
                    canonical=value,
                    aliases=[value],
                    confidence=1.0,
                    reason="kept separate",
                )
                for value in payload["axis_candidates"]["outcome"]
            ]
        )


class InventedAxisMergeExtractor(DuplicateMechanicalObjectiveExtractor):
    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[candidate["objective_id"]],
                    question=candidate["question"],
                    material_scope=candidate["material_scope"],
                    variables=[
                        *candidate["variables"],
                        "laser power",
                    ],
                    outcomes=candidate["outcomes"],
                    requested_comparator=candidate["requested_comparator"],
                    confidence=candidate["confidence"],
                    reason="invalid plan invents an axis",
                )
                for candidate in payload["candidate_objectives"]
            ]
        )


class CrossObjectiveAxisMergeExtractor(DuplicateMechanicalObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            candidate_processes=["Selective Laser Melting"],
            possible_objectives=[
                "How do laser power and scanning speed affect yield strength and "
                "elongation?",
                "How does porosity influence corrosion potential and "
                "pitting potential?",
            ],
            evidence_density="high",
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How do laser power and scanning speed affect yield "
                        "strength and elongation?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=[
                        "laser power",
                        "scanning speed",
                    ],
                    outcomes=["yield strength", "elongation"],
                    requested_comparator=(
                        "Compare laser power and scanning speed effects on "
                        "mechanical properties."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="mechanical objective",
                ),
                StructuredResearchObjective(
                    question=(
                        "How does porosity influence corrosion potential and "
                        "pitting potential?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=["porosity"],
                    outcomes=["corrosion potential", "pitting potential"],
                    constraints=["Selective Laser Melting"],
                    requested_comparator=(
                        "Compare corrosion response across porosity conditions."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="corrosion objective",
                ),
            ]
        )

    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        groups: list[StructuredObjectiveMergeGroup] = []
        for candidate in payload["candidate_objectives"]:
            variables = list(candidate["variables"])
            if "yield strength" in candidate["outcomes"]:
                variables.append("porosity")
            groups.append(
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[candidate["objective_id"]],
                    question=candidate["question"],
                    material_scope=candidate["material_scope"],
                    variables=variables,
                    outcomes=candidate["outcomes"],
                    requested_comparator=candidate["requested_comparator"],
                    confidence=candidate["confidence"],
                    reason="invalid plan leaks axes between objectives",
                )
            )
        return StructuredObjectiveMergePlan(merged_objectives=groups)


class OppositeDirectionMergeExtractor(DuplicateMechanicalObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            possible_objectives=[
                "How does porosity affect density and roughness?",
                "How does density affect porosity and roughness?",
            ],
            evidence_density="high",
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question="How does porosity affect density and roughness?",
                    variables=["porosity"],
                    outcomes=["density", "roughness"],
                    seed_document_ids=["paper-1"],
                    reason="porosity objective",
                ),
                StructuredResearchObjective(
                    question="How does density affect porosity and roughness?",
                    variables=["density"],
                    outcomes=["porosity", "roughness"],
                    seed_document_ids=["paper-1"],
                    reason="density objective",
                ),
            ]
        )

    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in payload["candidate_objectives"]
                    ],
                    question="How does density affect porosity?",
                    variables=["density"],
                    outcomes=["porosity"],
                    reason="invalid opposite-direction merge",
                )
            ]
        )


class CrossCandidateAxisExtractor(FakeObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            possible_objectives=[
                "How does laser power affect porosity?",
                "How does heat treatment affect corrosion resistance?",
            ],
            evidence_density="high",
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question="How does laser power affect corrosion resistance?",
                    variables=["laser power"],
                    outcomes=["corrosion resistance"],
                    seed_document_ids=["paper-1"],
                )
            ]
        )


class AxisQuestionMismatchExtractor(FakeObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            possible_objectives=["How does scan strategy affect porosity?"],
            evidence_density="high",
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question="How does scan strategy affect porosity?",
                    material_scope=["316L stainless steel"],
                    variables=["scan strategy"],
                    outcomes=["porosity"],
                    seed_document_ids=["paper-1"],
                )
            ]
        )

    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            axis_groups=[
                StructuredAxisCanonicalizationGroup(
                    axis_type="material",
                    canonical="316L stainless steel",
                    aliases=["316L stainless steel"],
                    reason="unchanged",
                ),
                StructuredAxisCanonicalizationGroup(
                    axis_type="variable",
                    canonical="scanning strategy",
                    aliases=["scan strategy"],
                    reason="canonicalized spelling",
                ),
                StructuredAxisCanonicalizationGroup(
                    axis_type="outcome",
                    canonical="porosity",
                    aliases=["porosity"],
                    reason="unchanged",
                ),
            ]
        )


class UnmatchedSeedObjectiveExtractor(DuplicateMechanicalObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How does heat treatment affect mechanical properties?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=["heat treatment"],
                    outcomes=["mechanical properties"],
                    constraints=["Selective Laser Melting"],
                    requested_comparator="Compare heat-treatment effects on strength.",
                    seed_document_ids=["P002-heat-treatment.pdf"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="model returned a source filename instead of document id",
                )
            ]
        )


class MissingSeedObjectiveExtractor(FakeObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question="How does heat treatment affect corrosion resistance?",
                    material_scope=["316L stainless steel"],
                    variables=["heat treatment"],
                    outcomes=["corrosion resistance"],
                    constraints=["LPBF"],
                    seed_document_ids=[],
                    confidence=0.88,
                    reason="model omitted the source document binding",
                )
            ]
        )


class OmittedMaterialScopeExtractor(FakeObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question="How does laser power affect relative density?",
                    material_scope=[],
                    variables=["laser power"],
                    outcomes=["relative density"],
                    seed_document_ids=["paper-1", "paper-2"],
                    confidence=0.88,
                    reason="model omitted the shared material scope",
                )
            ]
        )


class OverbroadPersistedObjectiveExtractor(DuplicateMechanicalObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How do energy density, scanning speed, porosity, heat "
                        "treatment, and scan strategy affect yield strength?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=[
                        "energy density",
                        "scanning speed",
                        "porosity",
                        "heat treatment",
                        "scan strategy",
                    ],
                    outcomes=["yield strength"],
                    requested_comparator=(
                        "Compare reported yield strength across all process axes."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="persisted objective contains unrelated process axes",
                )
            ]
        )

    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            candidate_processes=["Selective Laser Melting"],
            candidate_properties=["yield strength"],
            changed_variables=["energy density", "scanning speed"],
            possible_objectives=[
                "How do energy density and scanning speed affect yield strength?"
            ],
            evidence_density="high",
            confidence=0.91,
            warnings=[],
        )

    def extract_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredEvidenceExtractions:
        self.unit_payloads.append(payload)
        return StructuredEvidenceExtractions(
            extractions=[
                StructuredEvidenceExtraction(
                    evidence_role="direct_result",
                    changed_variables=[
                        {
                            "name": "energy density",
                            "baseline_value": 80,
                            "target_value": 100,
                            "unit": "J/mm3",
                        },
                        {
                            "name": "scanning speed",
                            "baseline_value": 1000,
                            "target_value": 1200,
                            "unit": "mm/s",
                        },
                    ],
                    comparison={
                        "baseline_label": "condition A",
                        "target_label": "condition B",
                        "axis_names": ["energy density", "scanning speed"],
                        "comparable": True,
                        "incomparability_reasons": [],
                    },
                    reported_result={
                        "outcome": "yield strength",
                        "value": 450,
                        "unit": "MPa",
                        "direction": "increase",
                        "result_text": "Yield strength reached 450 MPa.",
                    },
                    attribution_scope="joint_effect",
                    scientific_context={
                        "material": [
                            {
                                "name": "family",
                                "value": "316L stainless steel",
                            }
                        ],
                        "sample": [{"name": "label", "value": "S1"}],
                        "process": [
                            {"name": "process", "value": "SLM"},
                        ],
                    },
                    resolution_status="resolved",
                    confidence=0.86,
                )
            ]
        )


class DisjointPropertyMergeExtractor(DuplicateMechanicalObjectiveExtractor):
    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        candidates = payload["candidate_objectives"]
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in candidates
                    ],
                    question=(
                        "How do SLM parameters affect densification, "
                        "microstructure, and mechanical properties of 316L "
                        "stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=merge_candidate_values(candidates, "variables"),
                    outcomes=merge_candidate_values(candidates, "outcomes"),
                    requested_comparator=(
                        "Compare all reported structural and mechanical outcomes "
                        "under one objective."
                    ),
                    confidence=0.9,
                    reason="invalid plan merges disjoint property directions",
                )
            ]
        )


class UnderSpecifiedMergeQuestionExtractor(DuplicateMechanicalObjectiveExtractor):
    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        self.merge_payloads.append(payload)
        candidates = payload["candidate_objectives"]
        structure_candidates = [
            candidate
            for candidate in candidates
            if "densification" in candidate["outcomes"]
        ]
        mechanical_candidates = [
            candidate
            for candidate in candidates
            if "yield strength" in candidate["outcomes"]
        ]
        return StructuredObjectiveMergePlan(
            merged_objectives=[
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in structure_candidates
                    ],
                    question=structure_candidates[0]["question"],
                    material_scope=structure_candidates[0]["material_scope"],
                    variables=structure_candidates[0]["variables"],
                    outcomes=structure_candidates[0]["outcomes"],
                    requested_comparator=structure_candidates[0]["requested_comparator"],
                    confidence=0.9,
                    reason="kept structure objective separate",
                ),
                StructuredObjectiveMergeGroup(
                    source_objective_ids=[
                        candidate["objective_id"]
                        for candidate in mechanical_candidates
                    ],
                    question=(
                        "What is the relationship between scanning speed and "
                        "the mechanical properties of 316L stainless steel?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=merge_candidate_values(
                        mechanical_candidates,
                        "variables",
                    ),
                    outcomes=merge_candidate_values(
                        mechanical_candidates,
                        "outcomes",
                    ),
                    requested_comparator=(
                        "Examine how variations in scanning speed influence "
                        "the mechanical properties of 316L stainless steel."
                    ),
                    confidence=0.9,
                    reason="merged overlapping mechanical objectives",
                ),
            ]
        )


class SingleMixedObjectiveExtractor(DuplicateMechanicalObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question=(
                        "How do energy density, scanning strategy, and scanning "
                        "speed affect densification, microstructure, yield strength, "
                        "ultimate tensile strength, elongation, and microhardness?"
                    ),
                    material_scope=["316L stainless steel"],
                    variables=[
                        "energy density",
                        "scanning strategy",
                        "scanning speed",
                    ],
                    outcomes=[
                        "densification",
                        "microstructure",
                        "yield strength",
                        "ultimate tensile strength",
                        "elongation",
                        "microhardness",
                    ],
                    requested_comparator=(
                        "Compare all reported structural and mechanical outcomes "
                        "under SLM parameter changes."
                    ),
                    seed_document_ids=["paper-1"],
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="invalidly mixed distinct property directions",
                )
            ]
        )


class DuplicateObjectiveIdExtractor(FakeObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        objective = StructuredResearchObjective(
            question="How does heat treatment affect corrosion resistance?",
            material_scope=["316L stainless steel"],
            variables=["heat treatment"],
            outcomes=["corrosion resistance"],
            constraints=["LPBF"],
            requested_comparator="compare heat treatment effects on corrosion",
            seed_document_ids=["paper-1"],
            excluded_document_ids=[],
            confidence=0.88,
            reason="duplicate objective emitted by model",
        )
        return StructuredResearchObjectives(objectives=[objective, objective])


def merge_candidate_values(
    candidates: list[dict[str, Any]],
    key: str,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        for value in candidate[key]:
            text = str(value or "").strip()
            normalized = text.casefold()
            if not text or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(text)
    return merged


__all__ = [
    "AxisQuestionMismatchExtractor",
    "BroadObjectiveExtractor",
    "CanonicalizingAxisExtractor",
    "CrossCandidateAxisExtractor",
    "CrossObjectiveAxisMergeExtractor",
    "DisjointPropertyMergeExtractor",
    "DroppedObjectiveMergeExtractor",
    "DuplicateMechanicalObjectiveExtractor",
    "DuplicateObjectiveIdExtractor",
    "InvalidAxisCanonicalizationExtractor",
    "InventedAxisMergeExtractor",
    "MissingSeedObjectiveExtractor",
    "OmittedMaterialScopeExtractor",
    "OppositeDirectionMergeExtractor",
    "OverbroadAxisCanonicalizationExtractor",
    "OverbroadPersistedObjectiveExtractor",
    "SingleMixedObjectiveExtractor",
    "UnderSpecifiedMergeQuestionExtractor",
    "UnmatchedSeedObjectiveExtractor",
]
