"""Direct PostgreSQL persistence for evaluation lineage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

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
    EvaluationFailureRecord,
    EvaluationGoldItemRecord,
    EvaluationGoldSetRecord,
    EvaluationPredictionItemRecord,
    EvaluationPredictionSnapshotRecord,
    EvaluationRunRecord,
    EvaluationScoreRecord,
)


class PostgresEvaluationRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_gold_set(
        self,
        gold_set: EvaluationGoldSet,
        gold_items: tuple[EvaluationGoldItem, ...],
    ) -> None:
        if any(item.gold_id != gold_set.gold_id for item in gold_items):
            raise ValueError("gold item does not belong to gold set")
        with self.session_factory.begin() as session:
            row = session.get(EvaluationGoldSetRecord, gold_set.gold_id)
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
                    updated_at=_now(),
                )
                session.add(row)
            else:
                row.version = gold_set.version
                row.target_layer = gold_set.target_layer
                row.metric_profile = gold_set.metric_profile
                row.description = gold_set.description
                row.metadata_json = _json_value(gold_set.metadata or {})
                row.updated_at = _now()
            session.flush()
            session.execute(
                delete(EvaluationGoldItemRecord).where(
                    EvaluationGoldItemRecord.gold_id == gold_set.gold_id
                )
            )
            session.add_all(
                EvaluationGoldItemRecord(
                    gold_item_id=item.gold_item_id,
                    gold_id=item.gold_id,
                    document_id=item.document_id,
                    family=item.family,
                    item_key=item.item_key,
                    payload=_json_value(item.payload),
                    evidence_refs=_json_value(item.evidence_refs),
                    metadata_json=_json_value(item.metadata or {}),
                )
                for item in gold_items
            )

    def read_gold_set(self, gold_id: str) -> EvaluationGoldSet | None:
        with self.session_factory() as session:
            row = session.get(EvaluationGoldSetRecord, gold_id)
            return _gold_set(row) if row is not None else None

    def list_gold_items(self, gold_id: str) -> tuple[EvaluationGoldItem, ...]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(EvaluationGoldItemRecord)
                .where(EvaluationGoldItemRecord.gold_id == gold_id)
                .order_by(
                    EvaluationGoldItemRecord.document_id,
                    EvaluationGoldItemRecord.family,
                    EvaluationGoldItemRecord.item_key,
                    EvaluationGoldItemRecord.gold_item_id,
                )
            )
            return tuple(_gold_item(row) for row in rows)

    def upsert_prediction_snapshot(
        self,
        snapshot: EvaluationPredictionSnapshot,
    ) -> None:
        with self.session_factory.begin() as session:
            row = session.get(EvaluationPredictionSnapshotRecord, snapshot.snapshot_id)
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
                    created_at=_now(),
                )
                session.add(row)
            else:
                row.target_layer = snapshot.target_layer
                row.fact_source = snapshot.fact_source
                row.system_context = _json_value(snapshot.system_context)
                row.artifact_counts = _json_value(snapshot.artifact_counts)
            session.flush()
            session.execute(
                delete(EvaluationPredictionItemRecord).where(
                    EvaluationPredictionItemRecord.snapshot_id == snapshot.snapshot_id
                )
            )
            session.add_all(
                EvaluationPredictionItemRecord(
                    snapshot_id=snapshot.snapshot_id,
                    item_id=item.item_id,
                    document_id=item.document_id,
                    family=item.family,
                    item_key=item.item_key,
                    payload=_json_value(item.payload),
                    source_refs=_json_value(item.source_refs),
                    confidence=item.confidence,
                )
                for item in snapshot.items
            )

    def read_prediction_snapshot(
        self,
        snapshot_id: str,
    ) -> EvaluationPredictionSnapshot | None:
        with self.session_factory() as session:
            row = session.get(EvaluationPredictionSnapshotRecord, snapshot_id)
            if row is None:
                return None
            items = session.scalars(
                select(EvaluationPredictionItemRecord)
                .where(EvaluationPredictionItemRecord.snapshot_id == snapshot_id)
                .order_by(
                    EvaluationPredictionItemRecord.document_id,
                    EvaluationPredictionItemRecord.family,
                    EvaluationPredictionItemRecord.item_key,
                    EvaluationPredictionItemRecord.item_id,
                )
            )
            return EvaluationPredictionSnapshot.from_mapping(
                {
                    "snapshot_id": row.snapshot_id,
                    "collection_id": row.collection_id,
                    "target_layer": row.target_layer,
                    "fact_source": row.fact_source,
                    "system_context": row.system_context,
                    "artifact_counts": row.artifact_counts,
                    "items": [_prediction_item(item).to_record() for item in items],
                }
            )

    def upsert_evaluation_run(self, run: EvaluationRun) -> None:
        if any(
            score.evaluation_run_id != run.evaluation_run_id for score in run.scores
        ):
            raise ValueError("evaluation score does not belong to run")
        if any(
            failure.evaluation_run_id != run.evaluation_run_id
            for failure in run.failures
        ):
            raise ValueError("evaluation failure does not belong to run")
        with self.session_factory.begin() as session:
            gold = session.get(EvaluationGoldSetRecord, run.gold_id)
            snapshot = session.get(
                EvaluationPredictionSnapshotRecord, run.prediction_snapshot_id
            )
            if gold is None or snapshot is None:
                raise ValueError("evaluation parents do not exist")
            if (
                gold.collection_id != run.collection_id
                or snapshot.collection_id != run.collection_id
            ):
                raise ValueError("evaluation parents must share collection")
            row = session.get(EvaluationRunRecord, run.evaluation_run_id)
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
            session.flush()
            session.execute(
                delete(EvaluationScoreRecord).where(
                    EvaluationScoreRecord.evaluation_run_id == run.evaluation_run_id
                )
            )
            session.execute(
                delete(EvaluationFailureRecord).where(
                    EvaluationFailureRecord.evaluation_run_id == run.evaluation_run_id
                )
            )
            session.add_all(_score_record(score) for score in run.scores)
            session.add_all(_failure_record(failure) for failure in run.failures)

    def read_evaluation_run(self, evaluation_run_id: str) -> EvaluationRun | None:
        with self.session_factory() as session:
            row = session.get(EvaluationRunRecord, evaluation_run_id)
            return _evaluation_run(session, row) if row is not None else None

    def list_evaluation_runs(self, collection_id: str) -> tuple[EvaluationRun, ...]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(EvaluationRunRecord)
                .where(EvaluationRunRecord.collection_id == collection_id)
                .order_by(
                    EvaluationRunRecord.created_at.desc(),
                    EvaluationRunRecord.evaluation_run_id.desc(),
                )
            )
            return tuple(_evaluation_run(session, row) for row in rows)


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


def _gold_item(row: EvaluationGoldItemRecord) -> EvaluationGoldItem:
    return EvaluationGoldItem.from_mapping(
        {
            "gold_item_id": row.gold_item_id,
            "gold_id": row.gold_id,
            "document_id": row.document_id,
            "family": row.family,
            "item_key": row.item_key,
            "payload": row.payload,
            "evidence_refs": row.evidence_refs,
            "metadata": row.metadata_json,
        }
    )


def _prediction_item(
    row: EvaluationPredictionItemRecord,
) -> EvaluationPredictionItem:
    return EvaluationPredictionItem.from_mapping(
        {
            "item_id": row.item_id,
            "document_id": row.document_id,
            "family": row.family,
            "item_key": row.item_key,
            "payload": row.payload,
            "source_refs": row.source_refs,
            "confidence": row.confidence,
        }
    )


def _evaluation_run(session: Session, row: EvaluationRunRecord) -> EvaluationRun:
    scores = session.scalars(
        select(EvaluationScoreRecord)
        .where(EvaluationScoreRecord.evaluation_run_id == row.evaluation_run_id)
        .order_by(
            EvaluationScoreRecord.family,
            EvaluationScoreRecord.metric,
            EvaluationScoreRecord.score_id,
        )
    )
    failures = session.scalars(
        select(EvaluationFailureRecord)
        .where(EvaluationFailureRecord.evaluation_run_id == row.evaluation_run_id)
        .order_by(
            EvaluationFailureRecord.document_id,
            EvaluationFailureRecord.family,
            EvaluationFailureRecord.failure_id,
        )
    )
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
            "scores": [_score(score).to_record() for score in scores],
            "failures": [_failure(failure).to_record() for failure in failures],
        }
    )


def _score_record(score: EvaluationScore) -> EvaluationScoreRecord:
    return EvaluationScoreRecord(
        score_id=score.score_id,
        evaluation_run_id=score.evaluation_run_id,
        document_id=score.document_id,
        family=score.family,
        metric=score.metric,
        value=score.value,
        numerator=score.numerator,
        denominator=score.denominator,
    )


def _score(row: EvaluationScoreRecord) -> EvaluationScore:
    return EvaluationScore.from_mapping(
        {
            "score_id": row.score_id,
            "evaluation_run_id": row.evaluation_run_id,
            "document_id": row.document_id,
            "family": row.family,
            "metric": row.metric,
            "value": row.value,
            "numerator": row.numerator,
            "denominator": row.denominator,
        }
    )


def _failure_record(failure: EvaluationFailure) -> EvaluationFailureRecord:
    return EvaluationFailureRecord(
        failure_id=failure.failure_id,
        evaluation_run_id=failure.evaluation_run_id,
        document_id=failure.document_id,
        family=failure.family,
        failure_type=failure.failure_type,
        likely_layer=failure.likely_layer,
        severity=failure.severity,
        gold_item_id=failure.gold_item_id,
        prediction_item_id=failure.prediction_item_id,
        gold=_json_value(failure.gold),
        prediction=_json_value(failure.prediction),
        reason=failure.reason,
        source_refs=_json_value(failure.source_refs),
    )


def _failure(row: EvaluationFailureRecord) -> EvaluationFailure:
    return EvaluationFailure.from_mapping(
        {
            "failure_id": row.failure_id,
            "evaluation_run_id": row.evaluation_run_id,
            "document_id": row.document_id,
            "family": row.family,
            "failure_type": row.failure_type,
            "likely_layer": row.likely_layer,
            "severity": row.severity,
            "gold_item_id": row.gold_item_id,
            "prediction_item_id": row.prediction_item_id,
            "gold": row.gold,
            "prediction": row.prediction,
            "reason": row.reason,
            "source_refs": row.source_refs,
        }
    )


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
