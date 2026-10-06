#!/usr/bin/env python3
"""Run a reproducible offline comparison against a prepared DatasetExport."""

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
RUN_MANIFEST_SCHEMA_VERSION = "feedback-offline-run-manifest.v1"


class ExperimentProtocolError(ValueError):
    """Raised when an offline artifact does not match the prepared protocol."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare prediction artifacts on the exact evaluation split from a "
            "prepared DatasetExport."
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
    # A comparison is only a completed experiment when both sides were
    # produced for the exact same eval set.  A single artifact is useful for
    # diagnostics, but must remain ``not_run`` at the report level so callers
    # cannot mistake a partial run for a baseline/candidate result.
    completed = (
        baseline["status"] == "completed"
        and experiment["status"] == "completed"
    )
    overall_status = "completed" if completed else "not_run"
    run_manifest = _run_manifest(
        protocol=protocol,
        baseline=baseline,
        experiment=experiment,
        weights=weights,
        status=overall_status,
        comparison=comparison,
    )
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": overall_status,
        "protocol": protocol,
        "baseline": baseline,
        "experiment": experiment,
        "comparison": comparison,
        "weights": weights,
        "run_manifest": run_manifest,
        "deployment": {"status": "not_run", "reason": "offline_protocol_only"},
    }
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


def _protocol_metadata(prepared: dict[str, Any]) -> dict[str, Any]:
    export = prepared.get("export")
    if not isinstance(export, dict):
        raise ExperimentProtocolError("prepared_export_missing")
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
        "prepared_schema_version": prepared.get("schema_version"),
        "experiment_mode": prepared.get("experiment_mode", "historical"),
        "experiment_plan_digest": prepared.get("experiment_plan_digest"),
        "prepared_digest": prepared.get("prepared_digest"),
        "dataset_id": export.get("dataset_id"),
        "export_id": export.get("export_id"),
        "collection_id": export.get("collection_id"),
        "export_manifest_digest": export.get("manifest_digest"),
        "export_provenance_digest": export.get("provenance_digest"),
        "export_content_digest": export.get("content_digest"),
        "dataset_type": export.get("dataset_type"),
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
        return {
            "status": "not_run",
            "reason": "no_weight_manifest",
            "artifact": {"status": "missing"},
        }
    weight_path = Path(path).expanduser().resolve()
    try:
        raw = weight_path.read_bytes()
    except FileNotFoundError as exc:
        raise ExperimentProtocolError(f"weights_manifest_not_found:{weight_path}") from exc
    except OSError as exc:
        raise ExperimentProtocolError(f"weights_manifest_unreadable:{weight_path}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ExperimentProtocolError(f"weights_manifest_malformed_utf8:{weight_path}") from exc
    except json.JSONDecodeError as exc:
        raise ExperimentProtocolError(f"weights_manifest_malformed_json:{exc.lineno}") from exc
    if not isinstance(value, dict):
        raise ExperimentProtocolError("weights_manifest_object_required")
    if value.get("export_manifest_digest") != protocol["export_manifest_digest"]:
        raise ExperimentProtocolError("weight_export_digest_mismatch")
    if value.get("revision") != protocol["revision"]:
        raise ExperimentProtocolError("weight_revision_mismatch")
    if value.get("seed") != protocol["seed"]:
        raise ExperimentProtocolError("weight_seed_mismatch")
    return {
        "status": "validated",
        "path": str(weight_path),
        "model_id": value.get("model_id"),
        "export_manifest_digest": value["export_manifest_digest"],
        "revision": value["revision"],
        "seed": value["seed"],
        "artifact": {
            "status": "provided",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_size": len(raw),
        },
    }


def _evaluate_artifact(
    path: str | Path | None,
    *,
    eval_rows: list[dict[str, Any]],
    dataset_type: str,
    label: str,
) -> dict[str, Any]:
    if path is None:
        return {
            "status": "not_run",
            "reason": "prediction_artifact_missing",
            "artifact": {"status": "missing"},
        }
    prediction_path = Path(path).expanduser().resolve()
    predictions, artifact = _read_prediction_artifact(prediction_path)
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
        "artifact": artifact,
        "metrics": metrics,
    }


def _run_manifest(
    *,
    protocol: dict[str, Any],
    baseline: dict[str, Any],
    experiment: dict[str, Any],
    weights: dict[str, Any],
    status: str,
    comparison: dict[str, Any],
) -> dict[str, Any]:
    """Build a stable input ledger without claiming a training run occurred."""

    artifacts = {
        "baseline_predictions": _manifest_artifact(baseline),
        "experiment_predictions": _manifest_artifact(experiment),
        "weights_manifest": _manifest_artifact(weights),
    }
    basis = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "protocol": protocol,
        "artifacts": artifacts,
    }
    return {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": _digest(basis),
        "dataset_id": protocol["dataset_id"],
        "export_id": protocol["export_id"],
        "export_manifest_digest": protocol["export_manifest_digest"],
        "export_provenance_digest": protocol["export_provenance_digest"],
        "export_content_digest": protocol["export_content_digest"],
        "prepared_digest": protocol["prepared_digest"],
        "dataset_type": protocol["dataset_type"],
        "revision": protocol["revision"],
        "seed": protocol["seed"],
        "eval_row_ids_digest": protocol["eval_row_ids_digest"],
        "artifacts": artifacts,
        "status": status,
        "comparison_status": comparison.get("status"),
    }


def _manifest_artifact(value: dict[str, Any]) -> dict[str, Any]:
    artifact = value.get("artifact")
    if not isinstance(artifact, dict):
        return {"status": "unknown"}
    # Paths are useful in the detailed branch report, but make a poor identity
    # component because the same artifact can be mounted at different paths.
    return {key: item for key, item in artifact.items() if key != "path"}


def _metrics(
    eval_rows: list[dict[str, Any]], predictions: dict[str, dict[str, Any]], *, dataset_type: str
) -> dict[str, Any]:
    if dataset_type == "preference":
        chosen = 0
        invalid = 0
        for row in eval_rows:
            prediction = predictions[str(row["row_id"])]
            value = str(
                prediction.get("choice") or prediction.get("prediction") or ""
            ).strip().lower()
            if value == "chosen":
                chosen += 1
            elif value != "rejected":
                invalid += 1
        return {
            "evaluated": len(eval_rows),
            "chosen_rate": round(chosen / len(eval_rows), 4),
            "invalid_choices": invalid,
        }
    correct = 0
    scoreable = 0
    reference_missing = 0
    for row in eval_rows:
        prediction = str(predictions[str(row["row_id"])].get("prediction") or "")
        expected = row.get("reference") if dataset_type == "evaluation" else row.get("target")
        if dataset_type == "evaluation" and not _normalise_text(expected):
            reference_missing += 1
            continue
        scoreable += 1
        if _normalise_text(prediction) == _normalise_text(expected):
            correct += 1
    return {
        "evaluated": len(eval_rows),
        "scoreable": scoreable,
        "reference_missing": reference_missing,
        "correct": correct,
        "exact_match": round(correct / scoreable, 4) if scoreable else None,
    }


def _compare(baseline: dict[str, Any], experiment: dict[str, Any]) -> dict[str, Any]:
    if baseline.get("status") != "completed" or experiment.get("status") != "completed":
        return {"status": "not_run", "reason": "both_prediction_artifacts_required"}
    baseline_metrics = baseline["metrics"]
    experiment_metrics = experiment["metrics"]
    if "exact_match" in baseline_metrics:
        if baseline_metrics["exact_match"] is None or experiment_metrics["exact_match"] is None:
            return {"status": "not_comparable", "reason": "no_scoreable_eval_references"}
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
    return _read_prediction_artifact(path)[0]


def _read_prediction_artifact(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ExperimentProtocolError(f"prediction_artifact_not_found:{path}") from exc
    except OSError as exc:
        raise ExperimentProtocolError(f"prediction_artifact_unreadable:{path}") from exc
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ExperimentProtocolError(f"prediction_artifact_malformed_utf8:{path}") from exc
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
    return predictions, {
        "status": "provided",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_size": len(raw),
        "line_count": sum(1 for line in lines if line.strip()),
    }


def _normalise_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    main()


__all__ = [
    "ExperimentProtocolError",
    "REPORT_SCHEMA_VERSION",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "run_experiment",
]
