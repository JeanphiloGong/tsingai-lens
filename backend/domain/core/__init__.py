"""Core domain models and judgment rules."""

from domain.core.comparison import (
    ComparisonAssessment,
    ComparisonRow,
    SCALAR_LIKE_RESULT_TYPES,
    evaluate_comparison_assessment,
)
from domain.core.document_profile import (
    DocumentProfile,
    DocumentProfileSummary,
    analyze_document_profile,
    summarize_document_profile_collection,
)
from domain.core.evidence_backbone import (
    BaselineReference,
    CORE_NEUTRAL_DOMAIN_PROFILE,
    CharacterizationObservation,
    EvidenceAnchor,
    MeasurementResult,
    SampleVariant,
    StructureFeature,
    TestCondition,
)

__all__ = [
    "BaselineReference",
    "CORE_NEUTRAL_DOMAIN_PROFILE",
    "CharacterizationObservation",
    "ComparisonAssessment",
    "ComparisonRow",
    "DocumentProfile",
    "DocumentProfileSummary",
    "EvidenceAnchor",
    "MeasurementResult",
    "SCALAR_LIKE_RESULT_TYPES",
    "SampleVariant",
    "StructureFeature",
    "TestCondition",
    "analyze_document_profile",
    "evaluate_comparison_assessment",
    "summarize_document_profile_collection",
]
