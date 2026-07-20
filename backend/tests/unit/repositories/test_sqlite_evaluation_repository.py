from __future__ import annotations

from domain.evaluation import (
    EvaluationFailure,
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    EvaluationScore,
)
from infra.persistence.sqlite import SqliteEvaluationRepository


def test_sqlite_evaluation_repository_round_trips_gold_snapshot_and_run(tmp_path):
    repository = SqliteEvaluationRepository(tmp_path / "lens.sqlite")
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
            payload={
                "sample": "sample-a",
                "metric": "yield_strength",
                "value": 520,
                "unit": "MPa",
            },
            evidence_refs=({"quote": "520 MPa"},),
            metadata={},
        ),
    )

    repository.upsert_gold_set(gold_set, gold_items)

    assert repository.read_gold_set("gold-v1") == gold_set
    assert repository.list_gold_items("gold-v1") == gold_items

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
                payload={
                    "sample": "sample-a",
                    "metric": "yield_strength",
                    "value": 510,
                    "unit": "MPa",
                },
                source_refs=({"anchor_id": "anc-1"},),
                confidence=0.8,
            ),
        ),
    )

    repository.upsert_prediction_snapshot(snapshot)

    assert repository.read_prediction_snapshot("snapshot-1") == snapshot

    run = EvaluationRun(
        evaluation_run_id="eval-1",
        collection_id="col-gold",
        gold_id="gold-v1",
        prediction_snapshot_id="snapshot-1",
        target_layer="core",
        fact_source="objective_first",
        metric_profile="materials_core_v1",
        status="ready_with_failures",
        summary={"measurement_recall": 1.0, "measurement_precision": 1.0},
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

    repository.upsert_evaluation_run(run)

    assert repository.read_evaluation_run("eval-1") == run
    assert repository.list_evaluation_runs("col-gold") == (run,)


def test_sqlite_evaluation_repository_replaces_gold_and_snapshot_items(tmp_path):
    repository = SqliteEvaluationRepository(tmp_path / "lens.sqlite")
    gold_set = EvaluationGoldSet(
        gold_id="gold-v1",
        collection_id="col-gold",
        version="v1",
        target_layer="core",
        metric_profile="materials_core_v1",
    )

    repository.upsert_gold_set(
        gold_set,
        (
            EvaluationGoldItem(
                gold_item_id="gold-1",
                gold_id="gold-v1",
                document_id="doc-1",
                family="measurement_results",
                item_key="old",
                payload={"metric": "old"},
            ),
        ),
    )
    repository.upsert_gold_set(
        gold_set,
        (
            EvaluationGoldItem(
                gold_item_id="gold-2",
                gold_id="gold-v1",
                document_id="doc-1",
                family="measurement_results",
                item_key="new",
                payload={"metric": "new"},
            ),
        ),
    )

    assert [item.gold_item_id for item in repository.list_gold_items("gold-v1")] == [
        "gold-2"
    ]
