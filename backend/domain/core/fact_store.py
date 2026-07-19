from __future__ import annotations

from dataclasses import dataclass

from domain.core.comparison import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    PairwiseComparisonRelation,
)


@dataclass(frozen=True)
class CoreFactSet:
    comparison_artifacts_ready: bool = False
    comparable_results: tuple[ComparableResult, ...] = ()
    collection_comparable_results: tuple[CollectionComparableResult, ...] = ()
    pairwise_comparison_relations: tuple[PairwiseComparisonRelation, ...] = ()
    comparison_rows: tuple[ComparisonRowRecord, ...] = ()

    @property
    def comparison_artifacts_generated(self) -> bool:
        return bool(self.comparison_artifacts_ready)

__all__ = ["CoreFactSet"]
