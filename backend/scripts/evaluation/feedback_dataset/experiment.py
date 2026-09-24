#!/usr/bin/env python3
"""Run a reproducible offline comparison against a prepared P5 snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


def _prepare_api():
    try:
        from .prepare import SnapshotValidationError, load_prepared
    except ImportError:
        path = Path(__file__).with_name("prepare.py")
        spec = importlib.util.spec_from_file_location("feedback_dataset_prepare_runtime", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("offline prepare module is unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        SnapshotValidationError = module.SnapshotValidationError
        load_prepared = module.load_prepared
    return SnapshotValidationError, load_prepared


_SnapshotValidationError, _load_prepared = _prepare_api()


REPORT_SCHEMA_VERSION = "feedback-offline-experiment-report.v1"


class ExperimentProtocolError(ValueError):
    """Raised when an offline artifact does not match the prepared protocol."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare prediction artifacts on the exact evaluation split from a "
            "prepared feedback snapshot."
        )
    )
    parser.add_argument("prepared_dir", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--baseline-predictions", type=Path)
    parser.add_argument("--experiment-predictions", type=Path)
    parser.add_argument("--weights-manifest", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_experiment(
        prepared_dir=args.prepared_dir,
        output_path=args.output_path,
        baseline_predictions=args.baseline_predictions,
        experiment_predictions=args.experiment_predictions,
        weights_manifest=args.weights_manifest,
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))


def run_experiment(
    *,
    prepared_dir: str | Path,
    output_path: str | Path,
    baseline_predictions: str | Path | None = None,
    experiment_predictions: str | Path | None = None,
    weights_manifest: str | Path | None = None,
) -> dict[str, Any]:
    """Produce an auditable report without changing online model state.

    Prediction artifacts are deliberately an input boundary. A training
    runtime may create them, but this script never invents a model result when
    that runtime is absent. Missing artifacts therefore produce ``not_run``.
    """

    try:
        prepared = _load_prepared(prepared_dir)
    except _SnapshotValidationError as exc:
        raise ExperimentProtocolError(str(exc)) from exc
    protocol = _protocol_metadata(prepared)
    weights = _validate_weights_manifest(weights_manifest, protocol)
    eval_rows = list((prepared.get("rows_by_split") or {}).get("eval") or [])
    if not eval_rows:
        raise ExperimentProtocolError("eval_split_empty")

    baseline = _evaluate_artifact(
        baseline_predictions,
        eval_rows=eval_rows,
        dataset_type=str(protocol["dataset_type"]),
        label="baseline",
    )
    experiment = _evaluate_artifact(
        experiment_predictions,
        eval_rows=eval_rows,
        dataset_type=str(protocol["dataset_type"]),
        label="experiment",
    )
    comparison = _compare(baseline, experiment)
    completed = baseline["status"] == "completed" or experiment["status"] == "completed"
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "completed" if completed else "not_run",
        "protocol": protocol,
        "baseline": baseline,
        "experiment": experiment,
        "comparison": comparison,
        "weights": weights,
        "deployment": {"status": "not_run", "reason": "offline_protocol_only"},
    }
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


def _protocol_metadata(prepared: dict[str, Any]) -> dict[str, Any]:
    snapshot = prepared.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ExperimentProtocolError("prepared_snapshot_missing")
    rows_by_split = prepared.get("rows_by_split")
    if not isinstance(rows_by_split, dict):
        raise ExperimentProtocolError("prepared_rows_missing")
    eval_rows = rows_by_split.get("eval")
    if not isinstance(eval_rows, list):
        raise ExperimentProtocolError("prepared_eval_missing")
    row_ids = [str(row.get("row_id") or "") for row in eval_rows]
    if any(not row_id for row_id in row_ids) or len(set(row_ids)) != len(row_ids):
        raise ExperimentProtocolError("eval_row_ids_invalid")
    return {
        "snapshot_id": snapshot.get("dataset_id"),
        "snapshot_manifest_digest": snapshot.get("manifest_digest"),
        "snapshot_provenance_digest": snapshot.get("provenance_digest"),
        "snapshot_content_digest": snapshot.get("content_digest"),
        "dataset_type": snapshot.get("dataset_type"),
        "revision": prepared.get("revision"),
        "seed": prepared.get("seed"),
        "tokenizer": prepared.get("tokenizer"),
        "eval_row_ids_digest": _digest(sorted(row_ids)),
        "eval_row_count": len(row_ids),
    }


def _validate_weights_manifest(
    path: str | Path | None, protocol: dict[str, Any]
) -> dict[str, Any]:
    if path is None:
        return {"status": "not_run", "reason": "no_weight_manifest"}
    weight_path = Path(path).expanduser().resolve()
    try:
        value = json.loads(weight_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExperimentProtocolError(f"weights_manifest_not_found:{weight_path}") from exc
    except json.JSONDecodeError as exc:
        raise ExperimentProtocolError(f"weights_manifest_malformed_json:{exc.lineno}") from exc
    if not isinstance(value, dict):
        raise ExperimentProtocolError("weights_manifest_object_required")
    if value.get("snapshot_manifest_digest") != protocol["snapshot_manifest_digest"]:
        raise ExperimentProtocolError("weight_snapshot_digest_mismatch")
    if value.get("revision") != protocol["revision"]:
        raise ExperimentProtocolError("weight_revision_mismatch")
    if value.get("seed") != protocol["seed"]:
        raise ExperimentProtocolError("weight_seed_mismatch")
    return {
        "status": "validated",
        "path": str(weight_path),
        "model_id": value.get("model_id"),
        "snapshot_manifest_digest": value["snapshot_manifest_digest"],
        "revision": value["revision"],
        "seed": value["seed"],
    }


def _evaluate_artifact(
    path: str | Path | None,
    *,
    eval_rows: list[dict[str, Any]],
    dataset_type: str,
    label: str,
) -> dict[str, Any]:
    if path is None:
        return {"status": "not_run", "reason": "prediction_artifact_missing"}
    prediction_path = Path(path).expanduser().resolve()
    predictions = _read_predictions(prediction_path)
    expected_ids = {str(row["row_id"]) for row in eval_rows}
    actual_ids = set(predictions)
    if actual_ids != expected_ids:
        raise ExperimentProtocolError(
            f"eval_row_ids_mismatch:{label}:expected={len(expected_ids)}:actual={len(actual_ids)}"
        )
    metrics = _metrics(eval_rows, predictions, dataset_type=dataset_type)
    return {
        "status": "completed",
        "path": str(prediction_path),
        "metrics": metrics,
    }


def _metrics(
    eval_rows: list[dict[str, Any]], predictions: dict[str, dict[str, Any]], *, dataset_type: str
) -> dict[str, Any]:
    if dataset_type == "preference":
        chosen = 0
        for row in eval_rows:
            value = str(predictions[str(row["row_id"])].get("choice") or predictions[str(row["row_id"])].get("prediction") or "").strip().lower()
            if value == "chosen":
                chosen += 1
        return {
            "evaluated": len(eval_rows),
            "chosen_rate": round(chosen / len(eval_rows), 4),
        }
    correct = 0
    for row in eval_rows:
        prediction = str(predictions[str(row["row_id"])].get("prediction") or "")
        expected = row.get("reference") if dataset_type == "evaluation" else row.get("target")
        if _normalise_text(prediction) == _normalise_text(expected):
            correct += 1
    return {
        "evaluated": len(eval_rows),
        "correct": correct,
        "exact_match": round(correct / len(eval_rows), 4),
    }


def _compare(baseline: dict[str, Any], experiment: dict[str, Any]) -> dict[str, Any]:
    if baseline.get("status") != "completed" or experiment.get("status") != "completed":
        return {"status": "not_run", "reason": "both_prediction_artifacts_required"}
    baseline_metrics = baseline["metrics"]
    experiment_metrics = experiment["metrics"]
    if "exact_match" in baseline_metrics:
        return {
            "status": "completed",
            "exact_match_delta": round(
                experiment_metrics["exact_match"] - baseline_metrics["exact_match"], 4
            ),
        }
    return {
        "status": "completed",
        "chosen_rate_delta": round(
            experiment_metrics["chosen_rate"] - baseline_metrics["chosen_rate"], 4
        ),
    }


def _read_predictions(path: Path) -> dict[str, dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ExperimentProtocolError(f"prediction_artifact_not_found:{path}") from exc
    predictions: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExperimentProtocolError(f"prediction_malformed_json:{line_number}") from exc
        if not isinstance(value, dict) or not str(value.get("row_id") or "").strip():
            raise ExperimentProtocolError(f"prediction_row_invalid:{line_number}")
        row_id = str(value["row_id"])
        if row_id in predictions:
            raise ExperimentProtocolError(f"prediction_duplicate_row:{row_id}")
        predictions[row_id] = value
    return predictions


def _normalise_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    main()


__all__ = ["ExperimentProtocolError", "run_experiment"]
