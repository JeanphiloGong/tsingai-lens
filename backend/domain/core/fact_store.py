from __future__ import annotations

from dataclasses import dataclass

from domain.core.comparison import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    PairwiseComparisonRelation,
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
    comparison_artifacts_ready: bool = False
    paper_skims: tuple[PaperSkim, ...] = ()
    research_objectives: tuple[ResearchObjective, ...] = ()
    objective_contexts: tuple[ObjectiveContext, ...] = ()
    objective_paper_frames: tuple[ObjectivePaperFrame, ...] = ()
    objective_evidence_routes: tuple[ObjectiveEvidenceRoute, ...] = ()
    objective_evidence_units: tuple[ObjectiveEvidenceUnit, ...] = ()
    objective_logic_chains: tuple[ObjectiveLogicChain, ...] = ()
    comparable_results: tuple[ComparableResult, ...] = ()
    collection_comparable_results: tuple[CollectionComparableResult, ...] = ()
    pairwise_comparison_relations: tuple[PairwiseComparisonRelation, ...] = ()
    comparison_rows: tuple[ComparisonRowRecord, ...] = ()

    @property
    def comparison_artifacts_generated(self) -> bool:
        return bool(self.comparison_artifacts_ready)

__all__ = ["CoreFactSet"]
