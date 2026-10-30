"""PostgreSQL repository for evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from infra.persistence.database import AsyncSessionLocal

from domain.evaluation.records import (
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


class EvaluationRepository:
    backend_name = "postgresql"

    async def upsert_gold_set(
        self,
        gold_set: EvaluationGoldSet,
        gold_items: tuple[EvaluationGoldItem, ...],
    ) -> None:
        if any(item.gold_id != gold_set.gold_id for item in gold_items):
            raise ValueError("gold item does not belong to gold set")
        next_items = [
            {
                "gold_item_id": item.gold_item_id,
                "gold_id": item.gold_id,
                "document_id": item.document_id,
                "family": item.family,
                "item_key": item.item_key,
                "payload": dict(item.payload),
                "evidence_refs": [dict(ref) for ref in item.evidence_refs],
                "metadata": dict(item.metadata or {}),
            }
            for item in gold_items
        ]
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(EvaluationGoldSetRecord, gold_set.gold_id)
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
                    metadata_json=dict(gold_set.metadata or {}),
                    items=next_items,
                    updated_at=_now(),
                )
                db.add(row)
            else:
                row.version = gold_set.version
                row.target_layer = gold_set.target_layer
                row.metric_profile = gold_set.metric_profile
                row.description = gold_set.description
                row.metadata_json = dict(gold_set.metadata or {})
                row.items = next_items
                row.updated_at = _now()

    async def read_gold_set(self, gold_id: str) -> EvaluationGoldSet | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(EvaluationGoldSetRecord, gold_id)
            if row is None:
                return None
            return EvaluationGoldSet(
                gold_id=row.gold_id,
                collection_id=row.collection_id,
                version=row.version,
                target_layer=row.target_layer,
                metric_profile=row.metric_profile,
                description=row.description,
                metadata=dict(row.metadata_json or {}),
            )

    async def list_gold_items(self, gold_id: str) -> tuple[EvaluationGoldItem, ...]:
        async with AsyncSessionLocal() as db:
            row = await db.get(EvaluationGoldSetRecord, gold_id)
            if row is None:
                return ()
            return tuple(
                EvaluationGoldItem(
                    gold_item_id=item["gold_item_id"],
                    gold_id=item["gold_id"],
                    document_id=item["document_id"],
                    family=item["family"],
                    item_key=item["item_key"],
                    payload=dict(item["payload"]),
                    evidence_refs=tuple(dict(ref) for ref in item.get("evidence_refs", ())),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in _sorted_records(row.items)
            )

    async def upsert_prediction_snapshot(
        self,
        snapshot: EvaluationPredictionSnapshot,
    ) -> None:
        next_items = [
            {
                "item_id": item.item_id,
                "document_id": item.document_id,
                "family": item.family,
                "item_key": item.item_key,
                "payload": dict(item.payload),
                "source_refs": [dict(ref) for ref in item.source_refs],
                "confidence": item.confidence,
            }
            for item in snapshot.items
        ]
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(EvaluationPredictionSnapshotRecord, snapshot.snapshot_id)
            if row is not None and row.collection_id != snapshot.collection_id:
                raise ValueError("prediction snapshot identity cannot be reassigned")
            if row is None:
                row = EvaluationPredictionSnapshotRecord(
                    snapshot_id=snapshot.snapshot_id,
                    collection_id=snapshot.collection_id,
                    target_layer=snapshot.target_layer,
                    fact_source=snapshot.fact_source,
                    system_context=dict(snapshot.system_context),
                    artifact_counts=dict(snapshot.artifact_counts),
                    items=next_items,
                    created_at=_now(),
                )
                db.add(row)
            else:
                row.target_layer = snapshot.target_layer
                row.fact_source = snapshot.fact_source
                row.system_context = dict(snapshot.system_context)
                row.artifact_counts = dict(snapshot.artifact_counts)
                row.items = next_items

    async def read_prediction_snapshot(
        self,
        snapshot_id: str,
    ) -> EvaluationPredictionSnapshot | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(EvaluationPredictionSnapshotRecord, snapshot_id)
            if row is None:
                return None
            return EvaluationPredictionSnapshot(
                snapshot_id=row.snapshot_id,
                collection_id=row.collection_id,
                target_layer=row.target_layer,
                fact_source=row.fact_source,
                system_context=dict(row.system_context),
                artifact_counts=dict(row.artifact_counts),
                items=tuple(
                    EvaluationPredictionItem(
                        item_id=item["item_id"],
                        document_id=item["document_id"],
                        family=item["family"],
                        item_key=item["item_key"],
                        payload=dict(item["payload"]),
                        source_refs=tuple(dict(ref) for ref in item.get("source_refs", ())),
                        confidence=(
                            float(item["confidence"]) if item.get("confidence") is not None else None
                        ),
                    )
                    for item in _sorted_records(row.items)
                ),
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
        next_scores = [
            {
                "score_id": score.score_id,
                "evaluation_run_id": score.evaluation_run_id,
                "family": score.family,
                "metric": score.metric,
                "value": score.value,
                "numerator": score.numerator,
                "denominator": score.denominator,
                "document_id": score.document_id,
            }
            for score in run.scores
        ]
        next_failures = [
            {
                "failure_id": failure.failure_id,
                "evaluation_run_id": failure.evaluation_run_id,
                "document_id": failure.document_id,
                "family": failure.family,
                "failure_type": failure.failure_type,
                "likely_layer": failure.likely_layer,
                "severity": failure.severity,
                "gold_item_id": failure.gold_item_id,
                "prediction_item_id": failure.prediction_item_id,
                "gold": dict(failure.gold) if failure.gold is not None else None,
                "prediction": dict(failure.prediction) if failure.prediction is not None else None,
                "reason": failure.reason,
                "source_refs": [dict(ref) for ref in failure.source_refs],
            }
            for failure in run.failures
        ]
        async with AsyncSessionLocal() as db, db.begin():
            gold = await db.get(EvaluationGoldSetRecord, run.gold_id)
            snapshot = await db.get(
                EvaluationPredictionSnapshotRecord, run.prediction_snapshot_id
            )
            if gold is None or snapshot is None:
                raise ValueError("evaluation parents do not exist")
            if (
                gold.collection_id != run.collection_id
                or snapshot.collection_id != run.collection_id
            ):
                raise ValueError("evaluation parents must share collection")
            row = await db.get(EvaluationRunRecord, run.evaluation_run_id)
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
                    summary=dict(run.summary),
                    scores=next_scores,
                    failures=next_failures,
                    created_at=_now(),
                )
                db.add(row)
            else:
                row.gold_id = run.gold_id
                row.prediction_snapshot_id = run.prediction_snapshot_id
                row.target_layer = run.target_layer
                row.fact_source = run.fact_source
                row.metric_profile = run.metric_profile
                row.status = run.status
                row.summary = dict(run.summary)
                row.scores = next_scores
                row.failures = next_failures

    async def read_evaluation_run(self, evaluation_run_id: str) -> EvaluationRun | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(EvaluationRunRecord, evaluation_run_id)
            if row is None:
                return None
            return EvaluationRun(
                evaluation_run_id=row.evaluation_run_id,
                collection_id=row.collection_id,
                gold_id=row.gold_id,
                prediction_snapshot_id=row.prediction_snapshot_id,
                target_layer=row.target_layer,
                fact_source=row.fact_source,
                metric_profile=row.metric_profile,
                status=row.status,
                summary=dict(row.summary),
                scores=tuple(
                    EvaluationScore(
                        score_id=score["score_id"],
                        evaluation_run_id=score.get("evaluation_run_id", row.evaluation_run_id),
                        family=score["family"],
                        metric=score["metric"],
                        value=float(score["value"]),
                        numerator=float(score["numerator"]) if score.get("numerator") is not None else None,
                        denominator=float(score["denominator"]) if score.get("denominator") is not None else None,
                        document_id=score.get("document_id"),
                    )
                    for score in _sorted_records(row.scores)
                ),
                failures=tuple(
                    EvaluationFailure(
                        failure_id=failure["failure_id"],
                        evaluation_run_id=failure.get("evaluation_run_id", row.evaluation_run_id),
                        document_id=failure["document_id"],
                        family=failure["family"],
                        failure_type=failure["failure_type"],
                        likely_layer=failure["likely_layer"],
                        severity=failure["severity"],
                        gold_item_id=failure.get("gold_item_id"),
                        prediction_item_id=failure.get("prediction_item_id"),
                        gold=dict(failure["gold"]) if failure.get("gold") is not None else None,
                        prediction=dict(failure["prediction"]) if failure.get("prediction") is not None else None,
                        reason=failure.get("reason"),
                        source_refs=tuple(dict(ref) for ref in failure.get("source_refs", ())),
                    )
                    for failure in _sorted_records(row.failures)
                ),
            )

    async def list_evaluation_runs(self, collection_id: str) -> tuple[EvaluationRun, ...]:
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(
                select(EvaluationRunRecord)
                .where(EvaluationRunRecord.collection_id == collection_id)
                .order_by(
                    EvaluationRunRecord.created_at.desc(),
                    EvaluationRunRecord.evaluation_run_id.desc(),
                )
            )
            return tuple(
                EvaluationRun(
                    evaluation_run_id=row.evaluation_run_id,
                    collection_id=row.collection_id,
                    gold_id=row.gold_id,
                    prediction_snapshot_id=row.prediction_snapshot_id,
                    target_layer=row.target_layer,
                    fact_source=row.fact_source,
                    metric_profile=row.metric_profile,
                    status=row.status,
                    summary=dict(row.summary),
                    scores=tuple(
                        EvaluationScore(
                            score_id=score["score_id"],
                            evaluation_run_id=score.get("evaluation_run_id", row.evaluation_run_id),
                            family=score["family"],
                            metric=score["metric"],
                            value=float(score["value"]),
                            numerator=float(score["numerator"]) if score.get("numerator") is not None else None,
                            denominator=float(score["denominator"]) if score.get("denominator") is not None else None,
                            document_id=score.get("document_id"),
                        )
                        for score in _sorted_records(row.scores)
                    ),
                    failures=tuple(
                        EvaluationFailure(
                            failure_id=failure["failure_id"],
                            evaluation_run_id=failure.get("evaluation_run_id", row.evaluation_run_id),
                            document_id=failure["document_id"],
                            family=failure["family"],
                            failure_type=failure["failure_type"],
                            likely_layer=failure["likely_layer"],
                            severity=failure["severity"],
                            gold_item_id=failure.get("gold_item_id"),
                            prediction_item_id=failure.get("prediction_item_id"),
                            gold=dict(failure["gold"]) if failure.get("gold") is not None else None,
                            prediction=dict(failure["prediction"]) if failure.get("prediction") is not None else None,
                            reason=failure.get("reason"),
                            source_refs=tuple(dict(ref) for ref in failure.get("source_refs", ())),
                        )
                        for failure in _sorted_records(row.failures)
                    ),
                )
                for row in rows
            )


def _sorted_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda item: tuple(str(item.get(key, "")) for key in (
        "document_id", "family", "item_key", "metric", "failure_id", "score_id", "item_id", "gold_item_id"
    )))


def _now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ['EvaluationRepository', 'EvaluationRepo']


EvaluationRepo = EvaluationRepository()
