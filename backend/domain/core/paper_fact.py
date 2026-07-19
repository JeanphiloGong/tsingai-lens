from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class PaperFactSet:
    paper_facts_ready: bool = False
    document_profiles: tuple[DocumentProfile, ...] = ()
    evidence_anchors: tuple[EvidenceAnchor, ...] = ()
    method_facts: tuple[MethodFact, ...] = ()
    sample_variants: tuple[SampleVariant, ...] = ()
    test_conditions: tuple[TestCondition, ...] = ()
    baseline_references: tuple[BaselineReference, ...] = ()
    measurement_results: tuple[MeasurementResult, ...] = ()
    characterization_observations: tuple[CharacterizationObservation, ...] = ()
    structure_features: tuple[StructureFeature, ...] = ()

    @property
    def paper_facts_generated(self) -> bool:
        return self.paper_facts_ready

    @property
    def evidence_cards_generated(self) -> bool:
        return self.paper_facts_generated

    @property
    def evidence_cards_ready(self) -> bool:
        return bool(
            self.evidence_anchors or self.method_facts or self.measurement_results
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


__all__ = ["PaperFactSet"]
