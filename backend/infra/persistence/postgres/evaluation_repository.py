"""Direct PostgreSQL persistence for evaluation lineage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.evaluation import (
    EvaluationFailure,
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    EvaluationScore,
)
from infra.persistence.postgres.models.evaluation import (
    EvaluationGoldSetRecord,
    EvaluationPredictionSnapshotRecord,
    EvaluationRunRecord,
)


class PostgresEvaluationRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def upsert_gold_set(
        self,
        gold_set: EvaluationGoldSet,
        gold_items: tuple[EvaluationGoldItem, ...],
    ) -> None:
        if any(item.gold_id != gold_set.gold_id for item in gold_items):
            raise ValueError("gold item does not belong to gold set")
        async with self.session_factory.begin() as session:
            row = await session.get(EvaluationGoldSetRecord, gold_set.gold_id)
            if row is not None and row.collection_id != gold_set.collection_id:
                raise ValueError("gold set identity cannot be reassigned")
            if row is None:
                row = EvaluationGoldSetRecord(
                    gold_id=gold_set.gold_id,
                    collection_id=gold_set.collection_id,
                    version=gold_set.version,
                    target_layer=gold_set.target_layer,
                    metric_profile=gold_set.metric_profile,
                    description=gold_set.description,
                    metadata_json=_json_value(gold_set.metadata or {}),
                    items=_json_value(
                        [_gold_item_record(item) for item in gold_items]
                    ),
                    updated_at=_now(),
                )
                session.add(row)
            else:
                row.version = gold_set.version
                row.target_layer = gold_set.target_layer
                row.metric_profile = gold_set.metric_profile
                row.description = gold_set.description
                row.metadata_json = _json_value(gold_set.metadata or {})
                row.items = _json_value(
                    [_gold_item_record(item) for item in gold_items]
                )
                row.updated_at = _now()

    async def read_gold_set(self, gold_id: str) -> EvaluationGoldSet | None:
        async with self.session_factory() as session:
            row = await session.get(EvaluationGoldSetRecord, gold_id)
            return _gold_set(row) if row is not None else None

    async def list_gold_items(self, gold_id: str) -> tuple[EvaluationGoldItem, ...]:
        async with self.session_factory() as session:
            row = await session.get(EvaluationGoldSetRecord, gold_id)
            if row is None:
                return ()
            return tuple(
                EvaluationGoldItem.from_mapping(item)
                for item in _sorted_records(row.items)
            )

    async def upsert_prediction_snapshot(
        self,
        snapshot: EvaluationPredictionSnapshot,
    ) -> None:
        async with self.session_factory.begin() as session:
            row = await session.get(EvaluationPredictionSnapshotRecord, snapshot.snapshot_id)
            if row is not None and row.collection_id != snapshot.collection_id:
                raise ValueError("prediction snapshot identity cannot be reassigned")
            if row is None:
                row = EvaluationPredictionSnapshotRecord(
                    snapshot_id=snapshot.snapshot_id,
                    collection_id=snapshot.collection_id,
                    target_layer=snapshot.target_layer,
                    fact_source=snapshot.fact_source,
                    system_context=_json_value(snapshot.system_context),
                    artifact_counts=_json_value(snapshot.artifact_counts),
                    items=_json_value(
                        [_prediction_item_record(item) for item in snapshot.items]
                    ),
                    created_at=_now(),
                )
                session.add(row)
            else:
                row.target_layer = snapshot.target_layer
                row.fact_source = snapshot.fact_source
                row.system_context = _json_value(snapshot.system_context)
                row.artifact_counts = _json_value(snapshot.artifact_counts)
                row.items = _json_value(
                    [_prediction_item_record(item) for item in snapshot.items]
                )

    async def read_prediction_snapshot(
        self,
        snapshot_id: str,
    ) -> EvaluationPredictionSnapshot | None:
        async with self.session_factory() as session:
            row = await session.get(EvaluationPredictionSnapshotRecord, snapshot_id)
            if row is None:
                return None
            return EvaluationPredictionSnapshot.from_mapping(
                {
                    "snapshot_id": row.snapshot_id,
                    "collection_id": row.collection_id,
                    "target_layer": row.target_layer,
                    "fact_source": row.fact_source,
                    "system_context": row.system_context,
                    "artifact_counts": row.artifact_counts,
                    "items": [
                        _prediction_item_from_record(item).to_record()
                        for item in _sorted_records(row.items)
                    ],
                }
            )

    async def upsert_evaluation_run(self, run: EvaluationRun) -> None:
        if any(
            score.evaluation_run_id != run.evaluation_run_id for score in run.scores
        ):
            raise ValueError("evaluation score does not belong to run")
        if any(
            failure.evaluation_run_id != run.evaluation_run_id
            for failure in run.failures
        ):
            raise ValueError("evaluation failure does not belong to run")
        async with self.session_factory.begin() as session:
            gold = await session.get(EvaluationGoldSetRecord, run.gold_id)
            snapshot = await session.get(
                EvaluationPredictionSnapshotRecord, run.prediction_snapshot_id
            )
            if gold is None or snapshot is None:
                raise ValueError("evaluation parents do not exist")
            if (
                gold.collection_id != run.collection_id
                or snapshot.collection_id != run.collection_id
            ):
                raise ValueError("evaluation parents must share collection")
            row = await session.get(EvaluationRunRecord, run.evaluation_run_id)
            if row is not None and row.collection_id != run.collection_id:
                raise ValueError("evaluation run identity cannot be reassigned")
            if row is None:
                row = EvaluationRunRecord(
                    evaluation_run_id=run.evaluation_run_id,
                    collection_id=run.collection_id,
                    gold_id=run.gold_id,
                    prediction_snapshot_id=run.prediction_snapshot_id,
                    target_layer=run.target_layer,
                    fact_source=run.fact_source,
                    metric_profile=run.metric_profile,
                    status=run.status,
                    summary=_json_value(run.summary),
                    scores=_json_value([_score_record(score) for score in run.scores]),
                    failures=_json_value(
                        [_failure_record(failure) for failure in run.failures]
                    ),
                    created_at=_now(),
                )
                session.add(row)
            else:
                row.gold_id = run.gold_id
                row.prediction_snapshot_id = run.prediction_snapshot_id
                row.target_layer = run.target_layer
                row.fact_source = run.fact_source
                row.metric_profile = run.metric_profile
                row.status = run.status
                row.summary = _json_value(run.summary)
                row.scores = _json_value(
                    [_score_record(score) for score in run.scores]
                )
                row.failures = _json_value(
                    [_failure_record(failure) for failure in run.failures]
                )

    async def read_evaluation_run(self, evaluation_run_id: str) -> EvaluationRun | None:
        async with self.session_factory() as session:
            row = await session.get(EvaluationRunRecord, evaluation_run_id)
            return _evaluation_run(row) if row is not None else None

    async def list_evaluation_runs(self, collection_id: str) -> tuple[EvaluationRun, ...]:
        async with self.session_factory() as session:
            rows = await session.scalars(
                select(EvaluationRunRecord)
                .where(EvaluationRunRecord.collection_id == collection_id)
                .order_by(
                    EvaluationRunRecord.created_at.desc(),
                    EvaluationRunRecord.evaluation_run_id.desc(),
                )
            )
            return tuple(
                [_evaluation_run(row) for row in rows]
            )


def _gold_set(row: EvaluationGoldSetRecord) -> EvaluationGoldSet:
    return EvaluationGoldSet.from_mapping(
        {
            "gold_id": row.gold_id,
            "collection_id": row.collection_id,
            "version": row.version,
            "target_layer": row.target_layer,
            "metric_profile": row.metric_profile,
            "description": row.description,
            "metadata": row.metadata_json,
        }
    )


def _gold_item_record(item: EvaluationGoldItem) -> dict[str, Any]:
    return item.to_record()


def _prediction_item_record(item: EvaluationPredictionItem) -> dict[str, Any]:
    return item.to_record()


def _prediction_item_from_record(value: Any) -> EvaluationPredictionItem:
    return EvaluationPredictionItem.from_mapping(
        value if isinstance(value, dict) else {}
    )


def _evaluation_run(row: EvaluationRunRecord) -> EvaluationRun:
    return EvaluationRun.from_mapping(
        {
            "evaluation_run_id": row.evaluation_run_id,
            "collection_id": row.collection_id,
            "gold_id": row.gold_id,
            "prediction_snapshot_id": row.prediction_snapshot_id,
            "target_layer": row.target_layer,
            "fact_source": row.fact_source,
            "metric_profile": row.metric_profile,
            "status": row.status,
            "summary": row.summary,
            "scores": [
                _score_from_record(score, row.evaluation_run_id).to_record()
                for score in _sorted_records(row.scores)
            ],
            "failures": [
                _failure_from_record(failure, row.evaluation_run_id).to_record()
                for failure in _sorted_records(row.failures)
            ],
        }
    )


def _score_record(score: EvaluationScore) -> dict[str, Any]:
    return score.to_record()


def _score_from_record(value: Any, evaluation_run_id: str) -> EvaluationScore:
    record = dict(value) if isinstance(value, dict) else {}
    record.setdefault("evaluation_run_id", evaluation_run_id)
    return EvaluationScore.from_mapping(record)


def _failure_record(failure: EvaluationFailure) -> dict[str, Any]:
    return failure.to_record()


def _failure_from_record(value: Any, evaluation_run_id: str) -> EvaluationFailure:
    record = dict(value) if isinstance(value, dict) else {}
    record.setdefault("evaluation_run_id", evaluation_run_id)
    return EvaluationFailure.from_mapping(record)


def _sorted_records(value: Any) -> list[dict[str, Any]]:
    records = [item for item in value or () if isinstance(item, dict)]
    return sorted(records, key=lambda item: tuple(str(item.get(key) or "") for key in (
        "document_id", "family", "item_key", "metric", "failure_id", "score_id", "item_id", "gold_item_id"
    )))


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        return _json_value(value.tolist())
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        return _json_value(value.item())
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["PostgresEvaluationRepository"]
