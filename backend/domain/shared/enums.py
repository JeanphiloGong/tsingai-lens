from __future__ import annotations

from typing import Final, Literal, TypeAlias

DocumentType: TypeAlias = Literal["experimental", "mixed", "review", "uncertain"]

DOC_TYPE_EXPERIMENTAL: Final[DocumentType] = "experimental"
DOC_TYPE_MIXED: Final[DocumentType] = "mixed"
DOC_TYPE_REVIEW: Final[DocumentType] = "review"
DOC_TYPE_UNCERTAIN: Final[DocumentType] = "uncertain"

ProtocolExtractability: TypeAlias = Literal["yes", "partial", "no", "uncertain"]

PROTOCOL_EXTRACTABLE_YES: Final[ProtocolExtractability] = "yes"
PROTOCOL_EXTRACTABLE_PARTIAL: Final[ProtocolExtractability] = "partial"
PROTOCOL_EXTRACTABLE_NO: Final[ProtocolExtractability] = "no"
PROTOCOL_EXTRACTABLE_UNCERTAIN: Final[ProtocolExtractability] = "uncertain"
PROTOCOL_SUITABLE_EXTRACTABILITY: Final[frozenset[ProtocolExtractability]] = (
    frozenset(
        {
            PROTOCOL_EXTRACTABLE_YES,
            PROTOCOL_EXTRACTABLE_PARTIAL,
        }
    )
)

EpistemicStatus: TypeAlias = Literal[
    "directly_observed",
    "normalized_from_evidence",
    "inferred_from_characterization",
    "inferred_with_low_confidence",
    "unresolved",
]

EPISTEMIC_DIRECTLY_OBSERVED: Final[EpistemicStatus] = "directly_observed"
EPISTEMIC_NORMALIZED_FROM_EVIDENCE: Final[EpistemicStatus] = (
    "normalized_from_evidence"
)
EPISTEMIC_INFERRED_FROM_CHARACTERIZATION: Final[EpistemicStatus] = (
    "inferred_from_characterization"
)
EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE: Final[EpistemicStatus] = (
    "inferred_with_low_confidence"
)
EPISTEMIC_UNRESOLVED: Final[EpistemicStatus] = "unresolved"

ComparabilityStatus: TypeAlias = Literal[
    "comparable",
    "limited",
    "insufficient",
    "not_comparable",
]

COMPARABILITY_STATUS_COMPARABLE: Final[ComparabilityStatus] = "comparable"
COMPARABILITY_STATUS_LIMITED: Final[ComparabilityStatus] = "limited"
COMPARABILITY_STATUS_INSUFFICIENT: Final[ComparabilityStatus] = "insufficient"
COMPARABILITY_STATUS_NOT_COMPARABLE: Final[ComparabilityStatus] = "not_comparable"

TraceabilityStatus: TypeAlias = Literal["direct", "partial", "missing"]

TRACEABILITY_STATUS_DIRECT: Final[TraceabilityStatus] = "direct"
TRACEABILITY_STATUS_PARTIAL: Final[TraceabilityStatus] = "partial"
TRACEABILITY_STATUS_MISSING: Final[TraceabilityStatus] = "missing"

__all__ = [
    "COMPARABILITY_STATUS_COMPARABLE",
    "COMPARABILITY_STATUS_INSUFFICIENT",
    "COMPARABILITY_STATUS_LIMITED",
    "COMPARABILITY_STATUS_NOT_COMPARABLE",
    "DOC_TYPE_EXPERIMENTAL",
    "DOC_TYPE_MIXED",
    "DOC_TYPE_REVIEW",
    "DOC_TYPE_UNCERTAIN",
    "DocumentType",
    "EPISTEMIC_DIRECTLY_OBSERVED",
    "EPISTEMIC_INFERRED_FROM_CHARACTERIZATION",
    "EPISTEMIC_INFERRED_WITH_LOW_CONFIDENCE",
    "EPISTEMIC_NORMALIZED_FROM_EVIDENCE",
    "EPISTEMIC_UNRESOLVED",
    "EpistemicStatus",
    "PROTOCOL_EXTRACTABLE_NO",
    "PROTOCOL_EXTRACTABLE_PARTIAL",
    "PROTOCOL_EXTRACTABLE_UNCERTAIN",
    "PROTOCOL_EXTRACTABLE_YES",
    "PROTOCOL_SUITABLE_EXTRACTABILITY",
    "ProtocolExtractability",
    "TRACEABILITY_STATUS_DIRECT",
    "TRACEABILITY_STATUS_MISSING",
    "TRACEABILITY_STATUS_PARTIAL",
    "TraceabilityStatus",
]
