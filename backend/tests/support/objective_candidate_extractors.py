from __future__ import annotations

from typing import Any

from application.core.objectives.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredEvidenceExtraction,
    StructuredEvidenceExtractions,
    StructuredPaperSkim,
    StructuredResearchObjective,
    StructuredResearchObjectives,
)
from tests.support.objective_extractor import (
    FakeObjectiveExtractor,
    paper_skim_study_outputs,
    paper_relationship_records,
    relationship_lineage,
)


def _records_matching(
    payload: dict[str, Any],
    *,
    variable: str | None = None,
    outcome: str | None = None,
) -> list[tuple[str, str, str, dict[str, Any], dict[str, Any]]]:
    return [
        record
        for record in paper_relationship_records(payload)
        if (
            variable is None
            or variable in (record[4].get("varied_factors") or ())
        )
        and (
            outcome is None
            or outcome == record[4].get("outcome")
        )
    ]


def _study(
    *,
    varied_factors: list[str],
    outcomes: list[str],
    material_scope: list[str] | None = None,
    process_context: list[str] | None = None,
    confidence: float = 0.91,
) -> dict[str, Any]:
    return {
        "design_type": "experimental",
        "claim_scope": "current_work",
        "material_scope": material_scope or [],
        "process_context": process_context or [],
        "relationships": [
            {
                "varied_factors": varied_factors,
                "outcome": outcome,
                "confidence": confidence,
            }
            for outcome in outcomes
        ],
        "confidence": confidence,
    }


class BroadObjectiveExtractor(FakeObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            **paper_skim_study_outputs(
                payload,
                [
                    _study(
                        material_scope=["316L stainless steel"],
                        process_context=["Selective Laser Melting"],
                        varied_factors=[
                            "energy density",
                            "scanning strategy",
                            "scanning speed",
                        ],
                        outcomes=["mechanical properties"],
                    )
                ],
            ),
            unresolved_signals=[],
            evidence_density="high",
            confidence=0.91,
            warnings=[],
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        records = paper_relationship_records(payload)
        source_relationship_ids, seed_document_ids = relationship_lineage(records)
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
                    seed_document_ids=seed_document_ids,
                    excluded_document_ids=[],
                    confidence=0.88,
                    reason="paper skim points to mechanical-property comparison",
                    source_relationship_ids=source_relationship_ids,
                )
            ]
        )


class DuplicateMechanicalObjectiveExtractor(BroadObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            **paper_skim_study_outputs(
                payload,
                [
                    _study(
                        material_scope=["316L stainless steel"],
                        process_context=["Selective Laser Melting"],
                        varied_factors=[
                            "energy density",
                            "scanning strategy",
                            "scanning speed",
                        ],
                        outcomes=["densification", "microstructure"],
                    ),
                    _study(
                        material_scope=["316L stainless steel"],
                        process_context=["Selective Laser Melting"],
                        varied_factors=["energy density", "scanning speed"],
                        outcomes=[
                            "yield strength",
                            "ultimate tensile strength",
                            "elongation",
                            "microhardness",
                        ],
                    ),
                    _study(
                        material_scope=["316L stainless steel"],
                        process_context=["Selective Laser Melting"],
                        varied_factors=["scanning strategy"],
                        outcomes=["yield strength", "microhardness"],
                    ),
                ],
            ),
            unresolved_signals=[],
            evidence_density="high",
            confidence=0.91,
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        structure_records = _records_matching(payload, outcome="densification")
        broad_mechanical_records = _records_matching(
            payload,
            variable="energy density",
            outcome="ultimate tensile strength",
        )
        focused_mechanical_records = [
            record
            for record in _records_matching(payload, outcome="microhardness")
            if record[4].get("varied_factors") == ["scanning strategy"]
        ]
        structure_ids, structure_documents = relationship_lineage(structure_records)
        broad_ids, broad_documents = relationship_lineage(broad_mechanical_records)
        focused_ids, focused_documents = relationship_lineage(focused_mechanical_records)
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
                    seed_document_ids=structure_documents,
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="processing parameters affect density and structure",
                    source_relationship_ids=structure_ids,
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
                    seed_document_ids=broad_documents,
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="mechanical properties are reported together",
                    source_relationship_ids=broad_ids,
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
                    seed_document_ids=focused_documents,
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="mechanical properties overlap with the prior objective",
                    source_relationship_ids=focused_ids,
                ),
            ],
        )


class CanonicalizingAxisExtractor(DuplicateMechanicalObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            **paper_skim_study_outputs(
                payload,
                [
                    _study(
                        material_scope=["316L stainless steel"],
                        process_context=["Selective Laser Melting"],
                        varied_factors=[
                            "energy density",
                            "scan strategy",
                            "scanning speed",
                        ],
                        outcomes=["densification", "microstructure"],
                    ),
                    _study(
                        material_scope=["316L stainless steel"],
                        process_context=["Selective Laser Melting"],
                        varied_factors=["energy density", "scanning speed"],
                        outcomes=[
                            "yield strength",
                            "ultimate tensile strength",
                            "elongation",
                            "microhardness",
                        ],
                    ),
                    _study(
                        material_scope=["316L stainless steel"],
                        process_context=["Selective Laser Melting"],
                        varied_factors=["scan strategy"],
                        outcomes=["yield strength", "microhardness"],
                    ),
                ],
            ),
            unresolved_signals=[],
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
            decisions=[
                {
                    "pair_id": pair["pair_id"],
                    "equivalent": {
                        str(pair.get("left") or "").casefold(),
                        str(pair.get("right") or "").casefold(),
                    }
                    == {"scanning strategy", "scan strategy"},
                }
                for pair in payload.get("axis_pairs", ())
            ]
        )


class InvalidAxisCanonicalizationExtractor(CanonicalizingAxisExtractor):
    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        self.canonicalization_payloads.append(payload)
        return StructuredAxisCanonicalizationPlan(
            decisions=[{"pair_id": "unknown-pair", "equivalent": True}]
        )


class OverbroadAxisCanonicalizationExtractor(CanonicalizingAxisExtractor):
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


class CrossObjectiveAxisExtractor(DuplicateMechanicalObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            **paper_skim_study_outputs(
                payload,
                [
                    _study(
                        material_scope=["316L stainless steel"],
                        process_context=["Selective Laser Melting"],
                        varied_factors=["laser power", "scanning speed"],
                        outcomes=["yield strength", "elongation"],
                    ),
                    _study(
                        material_scope=["316L stainless steel"],
                        process_context=["Selective Laser Melting"],
                        varied_factors=["porosity"],
                        outcomes=["corrosion potential", "pitting potential"],
                    ),
                ],
            ),
            unresolved_signals=[],
            evidence_density="high",
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        mechanical_records = _records_matching(payload, outcome="yield strength")
        corrosion_records = _records_matching(payload, outcome="corrosion potential")
        mechanical_ids, mechanical_documents = relationship_lineage(mechanical_records)
        corrosion_ids, corrosion_documents = relationship_lineage(corrosion_records)
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
                    seed_document_ids=mechanical_documents,
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="mechanical objective",
                    source_relationship_ids=mechanical_ids,
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
                    seed_document_ids=corrosion_documents,
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="corrosion objective",
                    source_relationship_ids=corrosion_ids,
                ),
            ]
        )


class OppositeDirectionObjectiveExtractor(DuplicateMechanicalObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            **paper_skim_study_outputs(
                payload,
                [
                    _study(
                        varied_factors=["porosity"],
                        outcomes=["density", "roughness"],
                    ),
                    _study(
                        varied_factors=["density"],
                        outcomes=["porosity", "roughness"],
                    ),
                ],
            ),
            unresolved_signals=[],
            evidence_density="high",
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        porosity_records = _records_matching(payload, variable="porosity")
        density_records = _records_matching(payload, variable="density")
        porosity_ids, porosity_documents = relationship_lineage(porosity_records)
        density_ids, density_documents = relationship_lineage(density_records)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question="How does porosity affect density and roughness?",
                    variables=["porosity"],
                    outcomes=["density", "roughness"],
                    seed_document_ids=porosity_documents,
                    reason="porosity objective",
                    source_relationship_ids=porosity_ids,
                ),
                StructuredResearchObjective(
                    question="How does density affect porosity and roughness?",
                    variables=["density"],
                    outcomes=["porosity", "roughness"],
                    seed_document_ids=density_documents,
                    reason="density objective",
                    source_relationship_ids=density_ids,
                ),
            ]
        )


class CrossRelationshipAxisExtractor(FakeObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            **paper_skim_study_outputs(
                payload,
                [
                    _study(varied_factors=["laser power"], outcomes=["porosity"]),
                    _study(
                        varied_factors=["heat treatment"],
                        outcomes=["corrosion resistance"],
                    ),
                ],
            ),
            unresolved_signals=[],
            evidence_density="high",
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        laser_records = _records_matching(payload, variable="laser power")[:1]
        source_relationship_ids, seed_document_ids = relationship_lineage(laser_records)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question="How does laser power affect corrosion resistance?",
                    variables=["laser power"],
                    outcomes=["corrosion resistance"],
                    seed_document_ids=seed_document_ids,
                    source_relationship_ids=source_relationship_ids,
                )
            ]
        )


class AxisQuestionMismatchExtractor(FakeObjectiveExtractor):
    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            **paper_skim_study_outputs(
                payload,
                [
                    _study(
                        material_scope=["316L stainless steel"],
                        varied_factors=["scan strategy"],
                        outcomes=["porosity"],
                    )
                ],
            ),
            unresolved_signals=[],
            evidence_density="high",
        )

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        records = paper_relationship_records(payload)
        source_relationship_ids, seed_document_ids = relationship_lineage(records)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question="How does scan strategy affect porosity?",
                    material_scope=["316L stainless steel"],
                    variables=["scan strategy"],
                    outcomes=["porosity"],
                    seed_document_ids=seed_document_ids,
                    source_relationship_ids=source_relationship_ids,
                )
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


class UnmatchedSeedObjectiveExtractor(DuplicateMechanicalObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        records = paper_relationship_records(payload)
        selected_records = records[:1]
        source_relationship_ids, _ = relationship_lineage(selected_records)
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
                    source_relationship_ids=source_relationship_ids,
                )
            ]
        )


class MissingSeedObjectiveExtractor(FakeObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        records = paper_relationship_records(payload)
        source_relationship_ids, _ = relationship_lineage(records)
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
                    source_relationship_ids=source_relationship_ids,
                )
            ]
        )


class OmittedMaterialScopeExtractor(FakeObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        records = paper_relationship_records(payload)
        source_relationship_ids, seed_document_ids = relationship_lineage(records)
        return StructuredResearchObjectives(
            objectives=[
                StructuredResearchObjective(
                    question="How does laser power affect relative density?",
                    material_scope=[],
                    variables=["laser power"],
                    outcomes=["relative density"],
                    seed_document_ids=seed_document_ids,
                    confidence=0.88,
                    reason="model omitted the shared material scope",
                    source_relationship_ids=source_relationship_ids,
                )
            ]
        )


class OverbroadPersistedObjectiveExtractor(DuplicateMechanicalObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        records = paper_relationship_records(payload)
        source_relationship_ids, seed_document_ids = relationship_lineage(records)
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
                    seed_document_ids=seed_document_ids,
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="persisted objective contains unrelated process axes",
                    source_relationship_ids=source_relationship_ids,
                )
            ]
        )

    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        self.skim_payloads.append(payload)
        return StructuredPaperSkim(
            doc_role="experimental",
            **paper_skim_study_outputs(
                payload,
                [
                    _study(
                        material_scope=["316L stainless steel"],
                        process_context=["Selective Laser Melting"],
                        varied_factors=["energy density", "scanning speed"],
                        outcomes=["yield strength"],
                    )
                ],
            ),
            unresolved_signals=[],
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


class SingleMixedObjectiveExtractor(DuplicateMechanicalObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        records = paper_relationship_records(payload)
        source_relationship_ids, seed_document_ids = relationship_lineage(records)
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
                    seed_document_ids=seed_document_ids,
                    excluded_document_ids=[],
                    confidence=0.9,
                    reason="invalidly mixed distinct property directions",
                    source_relationship_ids=source_relationship_ids,
                )
            ]
        )


class DuplicateObjectiveIdExtractor(FakeObjectiveExtractor):
    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        self.discovery_payloads.append(payload)
        records = paper_relationship_records(payload)
        source_relationship_ids, seed_document_ids = relationship_lineage(records)
        objective = StructuredResearchObjective(
            question="How does heat treatment affect corrosion resistance?",
            material_scope=["316L stainless steel"],
            variables=["heat treatment"],
            outcomes=["corrosion resistance"],
            constraints=["LPBF"],
            requested_comparator="compare heat treatment effects on corrosion",
            seed_document_ids=seed_document_ids,
            excluded_document_ids=[],
            confidence=0.88,
            reason="duplicate objective emitted by model",
            source_relationship_ids=source_relationship_ids,
        )
        duplicate = objective.model_copy(update={"source_relationship_ids": []})
        return StructuredResearchObjectives(objectives=[objective, duplicate])


__all__ = [
    "AxisQuestionMismatchExtractor",
    "BroadObjectiveExtractor",
    "CanonicalizingAxisExtractor",
    "CrossRelationshipAxisExtractor",
    "CrossObjectiveAxisExtractor",
    "DuplicateMechanicalObjectiveExtractor",
    "DuplicateObjectiveIdExtractor",
    "InvalidAxisCanonicalizationExtractor",
    "MissingSeedObjectiveExtractor",
    "OmittedMaterialScopeExtractor",
    "OppositeDirectionObjectiveExtractor",
    "OverbroadAxisCanonicalizationExtractor",
    "OverbroadPersistedObjectiveExtractor",
    "SingleMixedObjectiveExtractor",
    "UnmatchedSeedObjectiveExtractor",
]
