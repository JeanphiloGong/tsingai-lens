from __future__ import annotations

from dataclasses import dataclass

from .source_ref import PaperResearchSourceRef


@dataclass(frozen=True)
class ReviewKnowledgeItem:
    """One review-author judgment or primary-paper navigation lead."""

    content: str
    material_scope: tuple[str, ...]
    variables: tuple[str, ...]
    outcomes: tuple[str, ...]
    conditions: tuple[str, ...]
    source_refs: tuple[PaperResearchSourceRef, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.source_refs:
            raise ValueError("review knowledge requires a source reference")


@dataclass(frozen=True)
class ReviewSynthesisMap:
    """Source-linked knowledge expressed by a review's authors."""

    synthesis_claims: tuple[ReviewKnowledgeItem, ...] = ()
    disputes: tuple[ReviewKnowledgeItem, ...] = ()
    evidence_gaps: tuple[ReviewKnowledgeItem, ...] = ()
    citation_leads: tuple[ReviewKnowledgeItem, ...] = ()


    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.synthesis_claims,
                self.disputes,
                self.evidence_gaps,
                self.citation_leads,
            )
        )
