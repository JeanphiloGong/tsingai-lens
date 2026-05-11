from __future__ import annotations

from dataclasses import dataclass

from domain.core.comparison import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
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
from domain.core.research_objective import PaperSkim, ResearchObjective


@dataclass(frozen=True)
class CoreFactSet:
    research_objectives_ready: bool = False
    paper_facts_ready: bool = False
    comparison_artifacts_ready: bool = False
    paper_skims: tuple[PaperSkim, ...] = ()
    research_objectives: tuple[ResearchObjective, ...] = ()
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
    comparison_rows: tuple[ComparisonRowRecord, ...] = ()

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
