from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from domain.evaluation import (
    EvaluationFailure,
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    EvaluationScore,
)
from domain.source import CollectionRecord
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.evaluation_repository import (
    PostgresEvaluationRepository,
)
pytestmark = pytest.mark.anyio


async def test_postgres_evaluation_repository_preserves_lineage_and_scope(
    postgres_session_factory,
) -> None:
    sessions = postgres_session_factory
    await PostgresAuthRepository(sessions).add_user(
        {
            "user_id": "user-evaluation",
            "email": "evaluation@example.com",
            "display_name": "Evaluation Reviewer",
            "password_hash": "synthetic-password-hash",
            "created_at": "2026-07-20T00:00:00+00:00",
        }
    )
    collections = PostgresCollectionRepository(sessions)
    for collection_id in ("col-gold", "col-other"):
        await collections.add_collection(
            CollectionRecord.from_mapping(
                {
                    "collection_id": collection_id,
                    "owner_user_id": "user-evaluation",
                    "name": collection_id,
                    "description": None,
                    "created_at": "2026-07-20T00:00:00+00:00",
                    "updated_at": "2026-07-20T00:00:00+00:00",
                    "status": "active",
                },
                collection_id,
                now_iso="2026-07-20T00:00:00+00:00",
            )
        )
    repository = PostgresEvaluationRepository(sessions)
    gold_set = EvaluationGoldSet(
        gold_id="gold-v1",
        collection_id="col-gold",
        version="v1",
        target_layer="core",
        metric_profile="materials_core_v1",
        description="LPBF 316L gold collection",
        metadata={"domain": "materials"},
    )
    gold_items = (
        EvaluationGoldItem(
            gold_item_id="gold-1",
            gold_id="gold-v1",
            document_id="doc-1",
            family="measurement_results",
            item_key="doc-1:sample-a:yield_strength",
            payload={"value": 520, "unit": "MPa"},
            evidence_refs=({"quote": "520 MPa"},),
            metadata={},
        ),
    )

    await repository.upsert_gold_set(gold_set, gold_items)

    assert await repository.read_gold_set("gold-v1") == gold_set
    assert await repository.list_gold_items("gold-v1") == gold_items

    snapshot = EvaluationPredictionSnapshot(
        snapshot_id="snapshot-1",
        collection_id="col-gold",
        target_layer="core",
        fact_source="objective_first",
        system_context={"model": "qwen"},
        artifact_counts={"objective_evidence_units": 1},
        items=(
            EvaluationPredictionItem(
                item_id="pred-1",
                document_id="doc-1",
                family="measurement_results",
                item_key="doc-1:sample-a:yield_strength",
                payload={"value": 510, "unit": "MPa"},
                source_refs=({"anchor_id": "anc-1"},),
                confidence=0.8,
            ),
        ),
    )
    await repository.upsert_prediction_snapshot(snapshot)
    assert await repository.read_prediction_snapshot("snapshot-1") == snapshot

    run = EvaluationRun(
        evaluation_run_id="eval-1",
        collection_id="col-gold",
        gold_id="gold-v1",
        prediction_snapshot_id="snapshot-1",
        target_layer="core",
        fact_source="objective_first",
        metric_profile="materials_core_v1",
        status="ready_with_failures",
        summary={"measurement_recall": 1.0},
        scores=(
            EvaluationScore(
                score_id="score-1",
                evaluation_run_id="eval-1",
                family="measurement_results",
                metric="recall",
                value=1.0,
                numerator=1.0,
                denominator=1.0,
            ),
        ),
        failures=(
            EvaluationFailure(
                failure_id="failure-1",
                evaluation_run_id="eval-1",
                document_id="doc-1",
                family="measurement_results",
                failure_type="numeric_value_mismatch",
                likely_layer="core_extraction",
                severity="high",
                gold_item_id="gold-1",
                prediction_item_id="pred-1",
                gold={"value": 520},
                prediction={"value": 510},
                reason="numeric value mismatch",
                source_refs=({"anchor_id": "anc-1"},),
            ),
        ),
    )
    await repository.upsert_evaluation_run(run)

    assert await repository.read_evaluation_run("eval-1") == run
    assert await repository.list_evaluation_runs("col-gold") == (run,)

    await repository.upsert_gold_set(
        gold_set,
        (
            EvaluationGoldItem(
                gold_item_id="gold-2",
                gold_id="gold-v1",
                document_id="doc-1",
                family="measurement_results",
                item_key="replacement",
                payload={"value": 525},
            ),
        ),
    )
    assert [
        item.gold_item_id
        for item in await repository.list_gold_items("gold-v1")
    ] == ["gold-2"]

    with pytest.raises(ValueError, match="gold set identity cannot be reassigned"):
        await repository.upsert_gold_set(
            EvaluationGoldSet(**{**gold_set.__dict__, "collection_id": "col-other"}),
            (),
        )

    await repository.upsert_prediction_snapshot(
        EvaluationPredictionSnapshot(
            snapshot_id="snapshot-other",
            collection_id="col-other",
            target_layer="core",
            fact_source="objective_first",
            system_context={},
            artifact_counts={},
            items=(),
        )
    )
    with pytest.raises(ValueError, match="evaluation parents must share collection"):
        await repository.upsert_evaluation_run(
            EvaluationRun(
                **{
                    **run.__dict__,
                    "evaluation_run_id": "eval-cross-collection",
                    "prediction_snapshot_id": "snapshot-other",
                    "scores": (),
                    "failures": (),
                }
            )
        )


async def test_postgresql_enforces_evaluation_foreign_keys_and_collection_cascade(
    postgres_session_factory,
) -> None:
    sessions = postgres_session_factory
    repository = PostgresEvaluationRepository(sessions)
    with pytest.raises(IntegrityError):
        await repository.upsert_gold_set(
            EvaluationGoldSet(
                gold_id="gold-orphan",
                collection_id="col-missing",
                version="v1",
                target_layer="core",
                metric_profile="materials_core_v1",
            ),
            (),
        )

    await PostgresAuthRepository(sessions).add_user(
        {
            "user_id": "user-evaluation-cascade",
            "email": "evaluation-cascade@example.com",
            "display_name": None,
            "password_hash": "synthetic-password-hash",
            "created_at": datetime(2026, 7, 20, tzinfo=timezone.utc).isoformat(),
        }
    )
    collections = PostgresCollectionRepository(sessions)
    await collections.add_collection(
        CollectionRecord.from_mapping(
            {
                "collection_id": "col-evaluation-cascade",
                "owner_user_id": "user-evaluation-cascade",
                "name": "Evaluation cascade",
                "description": None,
                "created_at": "2026-07-20T00:00:00+00:00",
                "updated_at": "2026-07-20T00:00:00+00:00",
                "status": "active",
            },
            "col-evaluation-cascade",
            now_iso="2026-07-20T00:00:00+00:00",
        )
    )
    await repository.upsert_gold_set(
        EvaluationGoldSet(
            gold_id="gold-cascade",
            collection_id="col-evaluation-cascade",
            version="v1",
            target_layer="core",
            metric_profile="materials_core_v1",
        ),
        (),
    )
    await repository.upsert_prediction_snapshot(
        EvaluationPredictionSnapshot(
            snapshot_id="snapshot-cascade",
            collection_id="col-evaluation-cascade",
            target_layer="core",
            fact_source="objective_first",
            system_context={},
            artifact_counts={},
            items=(),
        )
    )
    await repository.upsert_evaluation_run(
        EvaluationRun(
            evaluation_run_id="evaluation-cascade",
            collection_id="col-evaluation-cascade",
            gold_id="gold-cascade",
            prediction_snapshot_id="snapshot-cascade",
            target_layer="core",
            fact_source="objective_first",
            metric_profile="materials_core_v1",
            status="ready",
            summary={},
            scores=(
                EvaluationScore(
                    score_id="score-cascade",
                    evaluation_run_id="evaluation-cascade",
                    family="measurement_results",
                    metric="recall",
                    value=1.0,
                ),
            ),
            failures=(),
        )
    )

    assert await collections.delete_collection("col-evaluation-cascade") is True
    assert await repository.read_gold_set("gold-cascade") is None
    assert await repository.read_prediction_snapshot("snapshot-cascade") is None
    assert await repository.read_evaluation_run("evaluation-cascade") is None
