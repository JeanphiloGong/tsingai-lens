from __future__ import annotations

from dataclasses import dataclass

from domain.core.comparison import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    PairwiseComparisonRelation,
)
from domain.core.document_profile import DocumentProfile
from domain.core.evidence_backbone import (
    BaselineReference,
    CharacterizationObservation,
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    SampleVariant,
    StructureFeature,
    TestCondition,
)
from domain.core.research_objective import (
    ObjectiveContext,
    ObjectiveEvidenceRoute,
    ObjectiveEvidenceUnit,
    ObjectiveLogicChain,
    ObjectivePaperFrame,
    PaperSkim,
    ResearchObjective,
)


@dataclass(frozen=True)
class CoreFactSet:
    research_objectives_ready: bool = False
    paper_facts_ready: bool = False
    comparison_artifacts_ready: bool = False
    paper_skims: tuple[PaperSkim, ...] = ()
    research_objectives: tuple[ResearchObjective, ...] = ()
    objective_contexts: tuple[ObjectiveContext, ...] = ()
    objective_paper_frames: tuple[ObjectivePaperFrame, ...] = ()
    objective_evidence_routes: tuple[ObjectiveEvidenceRoute, ...] = ()
    objective_evidence_units: tuple[ObjectiveEvidenceUnit, ...] = ()
    objective_logic_chains: tuple[ObjectiveLogicChain, ...] = ()
    document_profiles: tuple[DocumentProfile, ...] = ()
    evidence_anchors: tuple[EvidenceAnchor, ...] = ()
    method_facts: tuple[MethodFact, ...] = ()
    sample_variants: tuple[SampleVariant, ...] = ()
    test_conditions: tuple[TestCondition, ...] = ()
    baseline_references: tuple[BaselineReference, ...] = ()
    measurement_results: tuple[MeasurementResult, ...] = ()
    characterization_observations: tuple[CharacterizationObservation, ...] = ()
    structure_features: tuple[StructureFeature, ...] = ()
    comparable_results: tuple[ComparableResult, ...] = ()
    collection_comparable_results: tuple[CollectionComparableResult, ...] = ()
    pairwise_comparison_relations: tuple[PairwiseComparisonRelation, ...] = ()
    comparison_rows: tuple[ComparisonRowRecord, ...] = ()

    @property
    def paper_facts_generated(self) -> bool:
        return bool(self.paper_facts_ready)

    @property
    def objective_evidence_units_ready(self) -> bool:
        return bool(self.objective_evidence_units)

    @property
    def evidence_cards_generated(self) -> bool:
        return bool(
            self.paper_facts_generated
            or self.objective_evidence_units_ready
        )

    @property
    def evidence_cards_ready(self) -> bool:
        return bool(
            self.evidence_anchors
            or self.method_facts
            or self.measurement_results
            or self.objective_evidence_units_ready
        )

    @property
    def comparison_artifacts_generated(self) -> bool:
        return bool(self.comparison_artifacts_ready)

    @property
    def graph_generated(self) -> bool:
        return bool(
            self.document_profiles
            and self.evidence_cards_generated
            and (
                self.objective_evidence_units_ready
                or self.comparison_artifacts_generated
            )
        )

    @property
    def graph_ready(self) -> bool:
        return bool(
            self.document_profiles
            and self.evidence_cards_ready
            and (
                self.objective_evidence_units_ready
                or self.objective_logic_chains
                or self.comparable_results
                or self.collection_comparable_results
                or self.comparison_rows
            )
        )

    def has_paper_facts(self) -> bool:
        return any(
            (
                self.document_profiles,
                self.evidence_anchors,
                self.method_facts,
                self.sample_variants,
                self.test_conditions,
                self.baseline_references,
                self.measurement_results,
                self.characterization_observations,
                self.structure_features,
            )
        )


__all__ = ["CoreFactSet"]
