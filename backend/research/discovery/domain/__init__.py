"""Paper Map and Source coverage domain objects."""

from research.discovery.domain.paper_map import (
    PaperResearchMap,
    PaperResearchRelationship,
    PaperResearchScope,
    PaperResearchSignal,
    PaperResearchSourceRef,
    PaperSourceUnitCoverage,
    PaperSourceUnitCoverageStatus,
    PreparedDocumentInput,
    build_paper_research_relationship,
    build_paper_research_scope,
    build_paper_research_scope_id,
    build_paper_research_signal,
)
from research.discovery.domain.review_map import ReviewKnowledgeItem, ReviewSynthesisMap

__all__ = [
    "PaperResearchMap",
    "PaperResearchRelationship",
    "PaperResearchScope",
    "PaperResearchSignal",
    "PaperResearchSourceRef",
    "PaperSourceUnitCoverage",
    "PaperSourceUnitCoverageStatus",
    "PreparedDocumentInput",
    "ReviewKnowledgeItem",
    "ReviewSynthesisMap",
    "build_paper_research_relationship",
    "build_paper_research_scope",
    "build_paper_research_scope_id",
    "build_paper_research_signal",
]
