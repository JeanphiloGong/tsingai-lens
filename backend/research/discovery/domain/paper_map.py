from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha1
from typing import Any

from .review_map import ReviewSynthesisMap

_PAPER_RESEARCH_VARIABLE_ROLES = frozenset(
    {"varied", "compared", "modeled", "fixed", "context", "uncertain"}
)

from .source_ref import PaperResearchSourceRef


@dataclass(frozen=True)
class PaperResearchRelationship:
    """One Source-supported joint-factor-to-outcome candidate-scope link."""

    relationship_id: str
    varied_factors: tuple[str, ...]
    outcome: str
    source_refs: tuple[PaperResearchSourceRef, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.varied_factors:
            raise ValueError("paper research relationship requires varied factors")
        if not self.source_refs:
            raise ValueError(
                "paper research relationship requires a source reference"
            )


_PAPER_RESEARCH_VARIABLE_ROLES = frozenset(
    {"varied", "compared", "modeled", "fixed", "context", "uncertain"}
)


@dataclass(frozen=True)
class PaperResearchScope:
    """One paper-owned research scope observed during preliminary reading."""

    study_id: str
    document_id: str
    design_type: str
    claim_scope: str
    experiment_label: str | None
    material_scope: tuple[str, ...]
    process_context: tuple[str, ...]
    relationships: tuple[PaperResearchRelationship, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.study_id.strip() or not self.document_id.strip():
            raise ValueError("paper research scope requires study and document ids")
        if not self.relationships:
            raise ValueError("paper research scope requires at least one relationship")
        relationship_ids = [item.relationship_id for item in self.relationships]
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ValueError("paper research relationship ids must be unique")





@dataclass(frozen=True)
class PaperResearchSignal:
    """One source-linked research axis awaiting a paper-scope link."""

    signal_id: str
    signal_type: str
    label: str
    variable_role: str
    design_type: str
    claim_scope: str
    experiment_label: str | None
    material_scope: tuple[str, ...]
    process_context: tuple[str, ...]
    source_refs: tuple[PaperResearchSourceRef, ...]
    confidence: float
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.signal_type == "variable" and (
            self.variable_role not in _PAPER_RESEARCH_VARIABLE_ROLES
        ):
            raise ValueError("variable signal requires a scientific variable role")
        if self.signal_type == "outcome" and self.variable_role != "not_applicable":
            raise ValueError("outcome signal variable role must be not_applicable")
        if not self.source_refs:
            raise ValueError("paper research signal requires at least one source")


class PaperSourceUnitCoverageStatus(StrEnum):
    RELATIONSHIP_EMITTED = "relationship_emitted"
    UNRESOLVED_SIGNAL_EMITTED = "unresolved_signal_emitted"
    NO_STUDY_SIGNAL = "no_study_signal"
    EXTRACTION_FAILED = "extraction_failed"


@dataclass(frozen=True)
class PaperSourceUnitCoverage:
    """First-stage extraction outcome for one Source unit."""

    source_unit_id: str
    window_id: str
    source_kind: str
    source_ref: str
    status: PaperSourceUnitCoverageStatus
    reason: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.source_unit_id,
                self.window_id,
                self.source_kind,
                self.source_ref,
            )
        ):
            raise ValueError("paper Source-unit coverage fields cannot be empty")
        if self.status in {
            PaperSourceUnitCoverageStatus.NO_STUDY_SIGNAL,
            PaperSourceUnitCoverageStatus.EXTRACTION_FAILED,
        }:
            if not self.reason:
                raise ValueError(
                    f"{self.status.value} Source-unit coverage requires a reason"
                )
        elif self.reason:
            raise ValueError(
                f"{self.status.value} Source-unit coverage cannot have a reason"
            )


@dataclass(frozen=True)
class PaperResearchMap:
    """Pre-Objective map of one paper's stated research scope."""

    document_id: str
    doc_role: str
    studies: tuple[PaperResearchScope, ...]
    evidence_density: str
    confidence: float
    warnings: tuple[str, ...]
    unresolved_signals: tuple[PaperResearchSignal, ...] = ()
    source_unit_coverage: tuple[PaperSourceUnitCoverage, ...] = ()
    map_status: str = "unknown"
    map_limitations: tuple[str, ...] = ()
    review_synthesis: ReviewSynthesisMap = field(default_factory=ReviewSynthesisMap)
    input_fingerprint: str | None = None
    map_version: str | None = None
    generated_at: str | None = None

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("paper research map requires document_id")
        if self.doc_role != "review" and not self.review_synthesis.is_empty:
            raise ValueError("review synthesis requires a review paper")
        if any(study.document_id != self.document_id for study in self.studies):
            raise ValueError(
                "paper research map contains a scope owned by another document"
            )
        study_ids = [study.study_id for study in self.studies]
        if len(study_ids) != len(set(study_ids)):
            raise ValueError("paper research map scope ids must be unique")
        coverage_ids = [item.source_unit_id for item in self.source_unit_coverage]
        if len(coverage_ids) != len(set(coverage_ids)):
            raise ValueError(
                "paper research map Source-unit coverage ids must be unique"
            )

    @property
    def coverage_complete(self) -> bool:
        return not any(
            item.status is PaperSourceUnitCoverageStatus.EXTRACTION_FAILED
            for item in self.source_unit_coverage
        )

@dataclass(frozen=True)
class PreparedDocumentInput:
    """Exact prepared document state consumed by one research operation."""

    document_id: str
    preparation_fingerprint: str

def build_paper_research_relationship(
    *,
    document_id: str,
    varied_factors: tuple[str, ...],
    outcome: str,
    source_refs: tuple[PaperResearchSourceRef, ...],
    confidence: float,
    parent_study_boundary: str | None = None,
) -> PaperResearchRelationship:
    identity = json.dumps(
        {
            'document_id': document_id.casefold(),
            'parent_study_boundary': parent_study_boundary,
            'varied_factors': sorted((value.casefold() for value in varied_factors)),
            'outcome': outcome.casefold(),
            'source_refs': sorted(((item.source_kind, item.source_ref) for item in source_refs)),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(',', ':'),
    )
    relationship_id = f"relationship_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
    return PaperResearchRelationship(
        relationship_id=relationship_id,
        varied_factors=varied_factors,
        outcome=outcome,
        source_refs=source_refs,
        confidence=confidence,
    )


def build_paper_research_scope(
    *,
    document_id: str,
    design_type: str,
    claim_scope: str,
    experiment_label: str | None,
    material_scope: tuple[str, ...],
    process_context: tuple[str, ...],
    relationships: tuple[PaperResearchRelationship, ...],
    confidence: float,
) -> PaperResearchScope:
    parent_study_boundary = json.dumps(
        {
            'document_id': document_id.casefold(),
            'design_type': design_type,
            'claim_scope': claim_scope,
            'experiment_label': experiment_label.casefold() if experiment_label else None,
            'material_scope': sorted((value.casefold() for value in material_scope)),
            'process_context': sorted((value.casefold() for value in process_context)),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(',', ':'),
    )
    relationships = tuple(build_paper_research_relationship(
        document_id=document_id,
        varied_factors=item.varied_factors,
        outcome=item.outcome,
        source_refs=item.source_refs,
        confidence=item.confidence,
        parent_study_boundary=parent_study_boundary,
    ) for item in relationships)
    study_id = build_paper_research_scope_id(
        document_id=document_id,
        design_type=design_type,
        claim_scope=claim_scope,
        experiment_label=experiment_label,
        material_scope=material_scope,
        process_context=process_context,
        relationships=relationships,
    )
    return PaperResearchScope(
        study_id=study_id,
        document_id=document_id,
        design_type=design_type,
        claim_scope=claim_scope,
        experiment_label=experiment_label,
        material_scope=material_scope,
        process_context=process_context,
        relationships=relationships,
        confidence=confidence,
    )


def build_paper_research_signal(
    *,
    document_id: str,
    signal_type: str,
    label: str,
    variable_role: str,
    design_type: str,
    claim_scope: str,
    experiment_label: str | None,
    material_scope: tuple[str, ...],
    process_context: tuple[str, ...],
    source_refs: tuple[PaperResearchSourceRef, ...],
    confidence: float,
    reason: str | None = None,
) -> PaperResearchSignal:
    identity = json.dumps(
        {
            'document_id': document_id.casefold(),
            'signal_type': signal_type,
            'label': label.casefold(),
            'variable_role': variable_role,
            'design_type': design_type,
            'claim_scope': claim_scope,
            'experiment_label': experiment_label.casefold() if experiment_label else None,
            'material_scope': sorted((value.casefold() for value in material_scope)),
            'process_context': sorted((value.casefold() for value in process_context)),
            'source_refs': sorted(((item.source_kind, item.source_ref) for item in source_refs)),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(',', ':'),
    )
    signal_id = f"signal_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
    return PaperResearchSignal(
        signal_id=signal_id,
        signal_type=signal_type,
        label=label,
        variable_role=variable_role,
        design_type=design_type,
        claim_scope=claim_scope,
        experiment_label=experiment_label,
        material_scope=material_scope,
        process_context=process_context,
        source_refs=source_refs,
        confidence=confidence,
        reason=reason,
    )


def build_paper_research_scope_id(
    *,
    document_id: str,
    design_type: str,
    claim_scope: str,
    experiment_label: str | None,
    material_scope: tuple[str, ...],
    process_context: tuple[str, ...],
    relationships: tuple[PaperResearchRelationship, ...],
) -> str:
    identity = json.dumps(
        {
            'document_id': document_id.casefold(),
            'design_type': design_type,
            'claim_scope': claim_scope,
            'experiment_label': experiment_label.casefold() if experiment_label else None,
            'material_scope': sorted((value.casefold() for value in material_scope)),
            'process_context': sorted((value.casefold() for value in process_context)),
            'relationship_ids': sorted((item.relationship_id for item in relationships)),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(',', ':'),
    )
    study_id = f"study_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
    return study_id
