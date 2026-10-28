"""PostgreSQL repository for evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.evaluation.records import (
    EVALUATION_FAILURE_TYPES,
    EVALUATION_LAYERS,
    EVALUATION_TARGET_LAYERS,
    EvaluationFailure,
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    EvaluationScore,
    _normalize_choice,
    _normalize_int_mapping,
    _normalize_mapping,
    _normalize_mapping_sequence,
    _normalize_mapping_tuple,
    _normalize_optional_float,
    _normalize_optional_mapping,
    _normalize_text,
)
from infra.persistence.postgres.models.evaluation import (
    EvaluationGoldSetRecord,
    EvaluationPredictionSnapshotRecord,
    EvaluationRunRecord,
)


class EvaluationRepository:
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
                    metadata_json=dict(gold_set.metadata or {}),
                    items=next_items,
                    updated_at=_now(),
                )
                session.add(row)
            else:
                row.version = gold_set.version
                row.target_layer = gold_set.target_layer
                row.metric_profile = gold_set.metric_profile
                row.description = gold_set.description
                row.metadata_json = dict(gold_set.metadata or {})
                row.items = next_items
                row.updated_at = _now()

    async def read_gold_set(self, gold_id: str) -> EvaluationGoldSet | None:
        async with self.session_factory() as session:
            row = await session.get(EvaluationGoldSetRecord, gold_id)
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
        async with self.session_factory() as session:
            row = await session.get(EvaluationGoldSetRecord, gold_id)
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
            return evaluation_prediction_snapshot_from_record(
                {
                    "snapshot_id": row.snapshot_id,
                    "collection_id": row.collection_id,
                    "target_layer": row.target_layer,
                    "fact_source": row.fact_source,
                    "system_context": row.system_context,
                    "artifact_counts": row.artifact_counts,
                    "items": [
                        evaluation_prediction_item_record(_prediction_item_from_record(item))
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


def _prediction_item_record(item: EvaluationPredictionItem) -> dict[str, Any]:
    return evaluation_prediction_item_record(item)


def _prediction_item_from_record(value: Any) -> EvaluationPredictionItem:
    return evaluation_prediction_item_from_record(
        value if isinstance(value, dict) else {}
    )


def _evaluation_run(row: EvaluationRunRecord) -> EvaluationRun:
    return evaluation_run_from_record(
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
                evaluation_score_record(_score_from_record(score, row.evaluation_run_id))
                for score in _sorted_records(row.scores)
            ],
            "failures": [
                evaluation_failure_record(_failure_from_record(failure, row.evaluation_run_id))
                for failure in _sorted_records(row.failures)
            ],
        }
    )


def _score_record(score: EvaluationScore) -> dict[str, Any]:
    return evaluation_score_record(score)


def _score_from_record(value: Any, evaluation_run_id: str) -> EvaluationScore:
    record = dict(value) if isinstance(value, dict) else {}
    record.setdefault("evaluation_run_id", evaluation_run_id)
    return evaluation_score_from_record(record)


def _failure_record(failure: EvaluationFailure) -> dict[str, Any]:
    return evaluation_failure_record(failure)


def _failure_from_record(value: Any, evaluation_run_id: str) -> EvaluationFailure:
    record = dict(value) if isinstance(value, dict) else {}
    record.setdefault("evaluation_run_id", evaluation_run_id)
    return evaluation_failure_from_record(record)


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


__all__ = ['EvaluationRepository']


def evaluation_prediction_item_from_record(payload: Mapping[str, Any]) -> EvaluationPredictionItem:
    return EvaluationPredictionItem(
        item_id=_normalize_text(payload.get("item_id")) or "",
        document_id=_normalize_text(payload.get("document_id")) or "",
        family=_normalize_text(payload.get("family")) or "",
        item_key=_normalize_text(payload.get("item_key")) or "",
        payload=_normalize_mapping(payload.get("payload")),
        source_refs=_normalize_mapping_tuple(payload.get("source_refs")),
        confidence=_normalize_optional_float(payload.get("confidence")),
    )


def evaluation_prediction_item_record(value: EvaluationPredictionItem) -> dict[str, Any]:
    return {"item_id": value.item_id, "document_id": value.document_id, "family": value.family,
            "item_key": value.item_key, "payload": dict(value.payload),
            "source_refs": [dict(item) for item in value.source_refs], "confidence": value.confidence}


def evaluation_prediction_snapshot_from_record(payload: Mapping[str, Any]) -> EvaluationPredictionSnapshot:
    return EvaluationPredictionSnapshot(
        snapshot_id=_normalize_text(payload.get("snapshot_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        target_layer=_normalize_choice(payload.get("target_layer"), allowed=EVALUATION_TARGET_LAYERS, default="core"),
        fact_source=_normalize_text(payload.get("fact_source")) or "paper_facts",
        system_context=_normalize_mapping(payload.get("system_context")),
        artifact_counts=_normalize_int_mapping(payload.get("artifact_counts")),
        items=tuple(evaluation_prediction_item_from_record(item) for item in _normalize_mapping_sequence(payload.get("items"))),
    )


def evaluation_prediction_snapshot_record(value: EvaluationPredictionSnapshot) -> dict[str, Any]:
    return {"snapshot_id": value.snapshot_id, "collection_id": value.collection_id,
            "target_layer": value.target_layer, "fact_source": value.fact_source,
            "system_context": dict(value.system_context), "artifact_counts": dict(value.artifact_counts),
            "items": [evaluation_prediction_item_record(item) for item in value.items]}


def evaluation_score_from_record(payload: Mapping[str, Any]) -> EvaluationScore:
    return EvaluationScore(
        score_id=_normalize_text(payload.get("score_id")) or "",
        evaluation_run_id=_normalize_text(payload.get("evaluation_run_id")) or "",
        family=_normalize_text(payload.get("family")) or "overall",
        metric=_normalize_text(payload.get("metric")) or "",
        value=_normalize_optional_float(payload.get("value")) or 0.0,
        numerator=_normalize_optional_float(payload.get("numerator")),
        denominator=_normalize_optional_float(payload.get("denominator")),
        document_id=_normalize_text(payload.get("document_id")),
    )


def evaluation_score_record(value: EvaluationScore) -> dict[str, Any]:
    return {"score_id": value.score_id, "evaluation_run_id": value.evaluation_run_id,
            "family": value.family, "metric": value.metric, "value": value.value,
            "numerator": value.numerator, "denominator": value.denominator, "document_id": value.document_id}


def evaluation_failure_from_record(payload: Mapping[str, Any]) -> EvaluationFailure:
    return EvaluationFailure(
        failure_id=_normalize_text(payload.get("failure_id")) or "",
        evaluation_run_id=_normalize_text(payload.get("evaluation_run_id")) or "",
        document_id=_normalize_text(payload.get("document_id")) or "",
        family=_normalize_text(payload.get("family")) or "",
        failure_type=_normalize_choice(payload.get("failure_type"), allowed=EVALUATION_FAILURE_TYPES, default="missing_gold_item"),
        likely_layer=_normalize_choice(payload.get("likely_layer"), allowed=EVALUATION_LAYERS, default="unknown"),
        severity=_normalize_text(payload.get("severity")) or "medium",
        gold_item_id=_normalize_text(payload.get("gold_item_id")),
        prediction_item_id=_normalize_text(payload.get("prediction_item_id")),
        gold=_normalize_optional_mapping(payload.get("gold")),
        prediction=_normalize_optional_mapping(payload.get("prediction")),
        reason=_normalize_text(payload.get("reason")),
        source_refs=_normalize_mapping_tuple(payload.get("source_refs")),
    )


def evaluation_failure_record(value: EvaluationFailure) -> dict[str, Any]:
    return {"failure_id": value.failure_id, "evaluation_run_id": value.evaluation_run_id,
            "document_id": value.document_id, "family": value.family, "failure_type": value.failure_type,
            "likely_layer": value.likely_layer, "severity": value.severity,
            "gold_item_id": value.gold_item_id, "prediction_item_id": value.prediction_item_id,
            "gold": dict(value.gold) if value.gold is not None else None,
            "prediction": dict(value.prediction) if value.prediction is not None else None,
            "reason": value.reason, "source_refs": [dict(item) for item in value.source_refs]}


def evaluation_run_from_record(payload: Mapping[str, Any]) -> EvaluationRun:
    return EvaluationRun(
        evaluation_run_id=_normalize_text(payload.get("evaluation_run_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        gold_id=_normalize_text(payload.get("gold_id")) or "",
        prediction_snapshot_id=_normalize_text(payload.get("prediction_snapshot_id")) or "",
        target_layer=_normalize_choice(payload.get("target_layer"), allowed=EVALUATION_TARGET_LAYERS, default="core"),
        fact_source=_normalize_text(payload.get("fact_source")) or "paper_facts",
        metric_profile=_normalize_text(payload.get("metric_profile")) or "materials_core_v1",
        status=_normalize_text(payload.get("status")) or "ready",
        summary=_normalize_mapping(payload.get("summary")),
        scores=tuple(evaluation_score_from_record(item) for item in _normalize_mapping_sequence(payload.get("scores"))),
        failures=tuple(evaluation_failure_from_record(item) for item in _normalize_mapping_sequence(payload.get("failures"))),
    )


def evaluation_run_record(value: EvaluationRun) -> dict[str, Any]:
    return {"evaluation_run_id": value.evaluation_run_id, "collection_id": value.collection_id,
            "gold_id": value.gold_id, "prediction_snapshot_id": value.prediction_snapshot_id,
            "target_layer": value.target_layer, "fact_source": value.fact_source,
            "metric_profile": value.metric_profile, "status": value.status, "summary": dict(value.summary),
            "scores": [evaluation_score_record(item) for item in value.scores],
            "failures": [evaluation_failure_record(item) for item in value.failures]}
