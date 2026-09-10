from __future__ import annotations

from typing import Protocol

from domain.evaluation import (
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionSnapshot,
    EvaluationRun,
)


class EvaluationRepository(Protocol):
    backend_name: str

    async def upsert_gold_set(
        self,
        gold_set: EvaluationGoldSet,
        gold_items: tuple[EvaluationGoldItem, ...],
    ) -> None: ...

    async def read_gold_set(
        self, gold_id: str
    ) -> EvaluationGoldSet | None: ...

    async def list_gold_items(
        self, gold_id: str
    ) -> tuple[EvaluationGoldItem, ...]: ...

    async def upsert_prediction_snapshot(
        self,
        snapshot: EvaluationPredictionSnapshot,
    ) -> None: ...

    async def read_prediction_snapshot(
        self,
        snapshot_id: str,
    ) -> EvaluationPredictionSnapshot | None: ...

    async def upsert_evaluation_run(self, run: EvaluationRun) -> None: ...

    async def read_evaluation_run(
        self, evaluation_run_id: str
    ) -> EvaluationRun | None: ...

    async def list_evaluation_runs(
        self, collection_id: str
    ) -> tuple[EvaluationRun, ...]: ...
