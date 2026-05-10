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


@dataclass(frozen=True)
class CoreFactSet:
    paper_facts_ready: bool = False
    comparison_artifacts_ready: bool = False
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


__all__ = ["CoreFactSet"]
