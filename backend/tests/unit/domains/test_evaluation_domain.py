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


def test_evaluation_gold_records_round_trip_collection_bound_contracts():
    gold_set = EvaluationGoldSet.from_mapping(
        {
            "gold_id": "lpbf_316l_gold_v1",
            "collection_id": "col_gold",
            "version": "v1",
            "target_layer": "core",
            "metric_profile": "materials_core_v1",
            "description": "LPBF 316L gold collection",
            "metadata": {"domain": "materials"},
        }
    )
    gold_item = EvaluationGoldItem.from_mapping(
        {
            "gold_item_id": "gold-measurement-1",
            "gold_id": gold_set.gold_id,
            "document_id": "doc-1",
            "family": "measurement_results",
            "item_key": "doc-1:sample-a:yield_strength",
            "payload": {
                "sample": "sample-a",
                "metric": "yield_strength",
                "value": 520,
                "unit": "MPa",
            },
            "evidence_refs": [{"document_id": "doc-1", "quote": "520 MPa"}],
        }
    )

    assert EvaluationGoldSet.from_mapping(gold_set.to_record()) == gold_set
    assert EvaluationGoldItem.from_mapping(gold_item.to_record()) == gold_item
    assert gold_set.collection_id == "col_gold"
    assert gold_item.family == "measurement_results"


def test_prediction_snapshot_and_evaluation_run_round_trip_failures():
    prediction_item = EvaluationPredictionItem.from_mapping(
        {
            "item_id": "pred-measurement-1",
            "document_id": "doc-1",
            "family": "measurement_results",
            "item_key": "doc-1:sample-a:yield_strength",
            "payload": {
                "metric": "yield_strength",
                "value": 510,
                "unit": "MPa",
            },
            "source_refs": [{"anchor_id": "anc-1"}],
            "confidence": "0.8",
        }
    )
    snapshot = EvaluationPredictionSnapshot.from_mapping(
        {
            "snapshot_id": "pred-1",
            "collection_id": "col_gold",
            "target_layer": "core",
            "fact_source": "objective_first",
            "system_context": {"model": "qwen"},
            "artifact_counts": {"measurement_results": "1"},
            "items": [prediction_item.to_record()],
        }
    )
    failure = EvaluationFailure.from_mapping(
        {
            "failure_id": "fail-1",
            "evaluation_run_id": "eval-1",
            "document_id": "doc-1",
            "family": "measurement_results",
            "failure_type": "numeric_value_mismatch",
            "likely_layer": "core_extraction",
            "severity": "high",
            "gold_item_id": "gold-measurement-1",
            "prediction_item_id": prediction_item.item_id,
            "gold": {"value": 520},
            "prediction": {"value": 510},
            "reason": "numeric value mismatch",
            "source_refs": [{"anchor_id": "anc-1"}],
        }
    )
    run = EvaluationRun.from_mapping(
        {
            "evaluation_run_id": "eval-1",
            "collection_id": "col_gold",
            "gold_id": "lpbf_316l_gold_v1",
            "prediction_snapshot_id": snapshot.snapshot_id,
            "target_layer": "core",
            "fact_source": "objective_first",
            "metric_profile": "materials_core_v1",
            "status": "ready_with_failures",
            "summary": {"measurement_recall": 1.0},
            "scores": [
                {
                    "score_id": "score-1",
                    "evaluation_run_id": "eval-1",
                    "family": "measurement_results",
                    "metric": "recall",
                    "value": 1,
                    "numerator": 1,
                    "denominator": 1,
                }
            ],
            "failures": [failure.to_record()],
        }
    )

    assert EvaluationPredictionSnapshot.from_mapping(snapshot.to_record()) == snapshot
    assert EvaluationRun.from_mapping(run.to_record()) == run
    assert snapshot.items[0].confidence == 0.8
    assert run.failures[0].likely_layer == "core_extraction"
    assert run.scores[0] == EvaluationScore.from_mapping(run.scores[0].to_record())
