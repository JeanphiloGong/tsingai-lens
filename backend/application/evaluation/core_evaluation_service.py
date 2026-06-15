from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from domain.evaluation import (
    EvaluationFailure,
    EvaluationGoldItem,
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    EvaluationScore,
)
from domain.ports import EvaluationRepository
from infra.persistence.factory import build_evaluation_repository


DEFAULT_ABSOLUTE_TOLERANCE = 1e-6
DEFAULT_RELATIVE_TOLERANCE = 1e-3
SCORED_FAMILIES = ("measurement_results", "comparisons")


class EvaluationInputNotFoundError(FileNotFoundError):
    """Raised when gold or prediction input is missing for an evaluation run."""


@dataclass(frozen=True)
class _MatchResult:
    family: str
    true_positive_count: int
    gold_count: int
    prediction_count: int
    failures: tuple[EvaluationFailure, ...]


class CoreEvaluationService:
    """Evaluate Core prediction snapshots against collection-bound gold sets."""

    def __init__(
        self,
        evaluation_repository: EvaluationRepository | None = None,
    ) -> None:
        self.evaluation_repository = (
            evaluation_repository or build_evaluation_repository()
        )

    def evaluate_snapshot(
        self,
        *,
        collection_id: str,
        gold_id: str,
        prediction_snapshot_id: str,
        evaluation_run_id: str | None = None,
        absolute_tolerance: float = DEFAULT_ABSOLUTE_TOLERANCE,
        relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
    ) -> EvaluationRun:
        gold_set = self.evaluation_repository.read_gold_set(gold_id)
        if gold_set is None or gold_set.collection_id != collection_id:
            raise EvaluationInputNotFoundError(f"gold set not found: {gold_id}")
        snapshot = self.evaluation_repository.read_prediction_snapshot(
            prediction_snapshot_id
        )
        if snapshot is None or snapshot.collection_id != collection_id:
            raise EvaluationInputNotFoundError(
                f"prediction snapshot not found: {prediction_snapshot_id}"
            )

        run_id = evaluation_run_id or f"eval_{collection_id}_{_timestamp_id()}"
        gold_items = self.evaluation_repository.list_gold_items(gold_id)
        results = tuple(
            self._evaluate_family(
                run_id=run_id,
                family=family,
                gold_items=tuple(item for item in gold_items if item.family == family),
                prediction_items=tuple(
                    item for item in snapshot.items if item.family == family
                ),
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            )
            for family in SCORED_FAMILIES
        )
        scores = tuple(
            score for result in results for score in self._scores(result, run_id)
        )
        failures = tuple(failure for result in results for failure in result.failures)
        summary = self._summary(results)
        run = EvaluationRun(
            evaluation_run_id=run_id,
            collection_id=collection_id,
            gold_id=gold_id,
            prediction_snapshot_id=snapshot.snapshot_id,
            target_layer="core",
            fact_source=snapshot.fact_source,
            metric_profile=gold_set.metric_profile,
            status="ready_with_failures" if failures else "ready",
            summary=summary,
            scores=scores,
            failures=failures,
        )
        self.evaluation_repository.upsert_evaluation_run(run)
        return run

    def _evaluate_family(
        self,
        *,
        run_id: str,
        family: str,
        gold_items: tuple[EvaluationGoldItem, ...],
        prediction_items: tuple[EvaluationPredictionItem, ...],
        absolute_tolerance: float,
        relative_tolerance: float,
    ) -> _MatchResult:
        predictions_by_key = {item.item_key: item for item in prediction_items}
        matched_prediction_ids: set[str] = set()
        failures: list[EvaluationFailure] = []
        true_positive_count = 0

        for gold in gold_items:
            prediction = predictions_by_key.get(gold.item_key)
            if prediction is None:
                failures.append(
                    self._failure(
                        run_id=run_id,
                        family=family,
                        failure_type="missing_gold_item",
                        gold=gold,
                        prediction=None,
                        reason="gold item has no matching prediction item",
                    )
                )
                continue

            matched_prediction_ids.add(prediction.item_id)
            item_failures = self._item_failures(
                run_id=run_id,
                family=family,
                gold=gold,
                prediction=prediction,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            )
            if item_failures:
                failures.extend(item_failures)
            else:
                true_positive_count += 1

        for prediction in prediction_items:
            if prediction.item_id in matched_prediction_ids:
                continue
            failures.append(
                self._failure(
                    run_id=run_id,
                    family=family,
                    failure_type="extra_prediction",
                    gold=None,
                    prediction=prediction,
                    reason="prediction item has no matching gold item",
                )
            )

        return _MatchResult(
            family=family,
            true_positive_count=true_positive_count,
            gold_count=len(gold_items),
            prediction_count=len(prediction_items),
            failures=tuple(failures),
        )

    def _item_failures(
        self,
        *,
        run_id: str,
        family: str,
        gold: EvaluationGoldItem,
        prediction: EvaluationPredictionItem,
        absolute_tolerance: float,
        relative_tolerance: float,
    ) -> list[EvaluationFailure]:
        failures: list[EvaluationFailure] = []
        if family == "measurement_results":
            if not self._numbers_match(
                self._numeric_value(gold.payload),
                self._numeric_value(prediction.payload),
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            ):
                failures.append(
                    self._failure(
                        run_id=run_id,
                        family=family,
                        failure_type="numeric_value_mismatch",
                        gold=gold,
                        prediction=prediction,
                        reason="measurement numeric value does not match gold",
                    )
                )
        if family == "comparisons":
            if not self._comparison_values_match(
                gold.payload,
                prediction.payload,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            ):
                failures.append(
                    self._failure(
                        run_id=run_id,
                        family=family,
                        failure_type="comparison_value_mismatch",
                        gold=gold,
                        prediction=prediction,
                        reason="comparison values do not match gold",
                    )
                )
            if self._text(gold.payload.get("direction")) and self._text(
                prediction.payload.get("direction")
            ) != self._text(gold.payload.get("direction")):
                failures.append(
                    self._failure(
                        run_id=run_id,
                        family=family,
                        failure_type="comparison_direction_mismatch",
                        gold=gold,
                        prediction=prediction,
                        reason="comparison direction does not match gold",
                    )
                )
        if self._text(gold.payload.get("unit")) != self._text(
            prediction.payload.get("unit")
        ):
            failures.append(
                self._failure(
                    run_id=run_id,
                    family=family,
                    failure_type="unit_mismatch",
                    gold=gold,
                    prediction=prediction,
                    reason="prediction unit does not match gold",
                )
            )
        if gold.evidence_refs and not prediction.source_refs:
            failures.append(
                self._failure(
                    run_id=run_id,
                    family=family,
                    failure_type="evidence_trace_missing",
                    gold=gold,
                    prediction=prediction,
                    reason="prediction does not include source references",
                )
            )
        return failures

    def _failure(
        self,
        *,
        run_id: str,
        family: str,
        failure_type: str,
        gold: EvaluationGoldItem | None,
        prediction: EvaluationPredictionItem | None,
        reason: str,
    ) -> EvaluationFailure:
        if gold is not None:
            document_id = gold.document_id
        elif prediction is not None:
            document_id = prediction.document_id
        else:
            document_id = ""
        identity_parts = [
            run_id,
            family,
            failure_type,
            gold.gold_item_id if gold is not None else "",
            prediction.item_id if prediction is not None else "",
        ]
        return EvaluationFailure(
            failure_id="fail_"
            + "_".join(_normalize_key(part) for part in identity_parts),
            evaluation_run_id=run_id,
            document_id=document_id,
            family=family,
            failure_type=failure_type,
            likely_layer=self._likely_layer(failure_type),
            severity="high" if failure_type == "missing_gold_item" else "medium",
            gold_item_id=gold.gold_item_id if gold is not None else None,
            prediction_item_id=prediction.item_id if prediction is not None else None,
            gold=gold.payload if gold is not None else None,
            prediction=prediction.payload if prediction is not None else None,
            reason=reason,
            source_refs=(
                prediction.source_refs
                if prediction is not None
                else gold.evidence_refs
                if gold is not None
                else ()
            ),
        )

    def _scores(self, result: _MatchResult, run_id: str) -> tuple[EvaluationScore, ...]:
        precision = _ratio(result.true_positive_count, result.prediction_count)
        recall = _ratio(result.true_positive_count, result.gold_count)
        return (
            EvaluationScore(
                score_id=f"score_{run_id}_{result.family}_precision",
                evaluation_run_id=run_id,
                family=result.family,
                metric="precision",
                value=precision,
                numerator=float(result.true_positive_count),
                denominator=float(result.prediction_count),
            ),
            EvaluationScore(
                score_id=f"score_{run_id}_{result.family}_recall",
                evaluation_run_id=run_id,
                family=result.family,
                metric="recall",
                value=recall,
                numerator=float(result.true_positive_count),
                denominator=float(result.gold_count),
            ),
        )

    def _summary(self, results: tuple[_MatchResult, ...]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        total_gold = 0
        total_predictions = 0
        total_true_positive = 0
        for result in results:
            precision = _ratio(result.true_positive_count, result.prediction_count)
            recall = _ratio(result.true_positive_count, result.gold_count)
            prefix = (
                "measurement"
                if result.family == "measurement_results"
                else "comparison"
            )
            summary[f"{prefix}_precision"] = precision
            summary[f"{prefix}_recall"] = recall
            summary[f"{prefix}_gold_count"] = result.gold_count
            summary[f"{prefix}_prediction_count"] = result.prediction_count
            summary[f"{prefix}_failure_count"] = len(result.failures)
            total_gold += result.gold_count
            total_predictions += result.prediction_count
            total_true_positive += result.true_positive_count
        summary["overall_precision"] = _ratio(total_true_positive, total_predictions)
        summary["overall_recall"] = _ratio(total_true_positive, total_gold)
        summary["failure_count"] = sum(len(result.failures) for result in results)
        return summary

    def _comparison_values_match(
        self,
        gold: dict[str, Any],
        prediction: dict[str, Any],
        *,
        absolute_tolerance: float,
        relative_tolerance: float,
    ) -> bool:
        gold_current = self._optional_numeric(gold.get("current_value"))
        gold_baseline = self._optional_numeric(gold.get("baseline_value"))
        prediction_current = self._optional_numeric(prediction.get("current_value"))
        prediction_baseline = self._optional_numeric(prediction.get("baseline_value"))
        if gold_current is not None or prediction_current is not None:
            return self._numbers_match(
                gold_current,
                prediction_current,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            ) and self._numbers_match(
                gold_baseline,
                prediction_baseline,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            )
        return True

    def _numbers_match(
        self,
        gold_value: float | None,
        prediction_value: float | None,
        *,
        absolute_tolerance: float,
        relative_tolerance: float,
    ) -> bool:
        if gold_value is None and prediction_value is None:
            return True
        if gold_value is None or prediction_value is None:
            return False
        diff = abs(gold_value - prediction_value)
        if diff <= absolute_tolerance:
            return True
        return diff <= relative_tolerance * max(
            abs(gold_value),
            abs(prediction_value),
            1.0,
        )

    def _numeric_value(self, payload: dict[str, Any]) -> float | None:
        for key in ("value", "numeric_value", "current_value"):
            value = self._optional_numeric(payload.get(key))
            if value is not None:
                return value
        value_payload = payload.get("value_payload")
        if isinstance(value_payload, dict):
            return self._numeric_value(value_payload)
        return None

    def _optional_numeric(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None

    def _likely_layer(self, failure_type: str) -> str:
        if failure_type in {"unit_mismatch", "comparison_direction_mismatch"}:
            return "core_normalization"
        return "core_extraction"


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return numerator / denominator


def _timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


def _normalize_key(value: str) -> str:
    return "_".join(str(value or "").strip().lower().split()) or "none"
