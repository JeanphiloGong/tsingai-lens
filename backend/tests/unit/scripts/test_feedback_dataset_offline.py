from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _load_module(name: str, relative_path: str):
    backend_root = Path(__file__).resolve().parents[3]
    script_path = backend_root / "scripts" / "evaluation" / "feedback_dataset" / relative_path
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def prepare_module():
    return _load_module("feedback_dataset_prepare", "prepare.py")


@pytest.fixture(scope="module")
def experiment_module():
    return _load_module("feedback_dataset_experiment", "experiment.py")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_cli(script_name: str, *arguments: object) -> subprocess.CompletedProcess[str]:
    backend_root = Path(__file__).resolve().parents[3]
    script_path = backend_root / "scripts" / "evaluation" / "feedback_dataset" / script_name
    return subprocess.run(
        [sys.executable, str(script_path), *(str(argument) for argument in arguments)],
        cwd=backend_root.parent,
        capture_output=True,
        text=True,
        check=False,
    )


def _snapshot(*, dataset_type: str = "evaluation", rows: list[dict] | None = None) -> dict:
    rows = rows or [
        {
            "split": "train",
            "record_type": dataset_type,
            "input": "Which source supports the claim?",
            "reference": "Source A supports the claim.",
            "evidence": [
                {
                    "document_title": "Paper A",
                    "quote": "Source A supports the claim.",
                    "heading_path": "Results",
                }
            ],
            "criteria": ["must cite source"],
        },
        {
            "split": "eval",
            "record_type": dataset_type,
            "input": "What did source B report?",
            "reference": "Source B reports a lower value.",
            "evidence": [
                {
                    "document_title": "Paper B",
                    "quote": "Source B reports a lower value.",
                    "page": 4,
                }
            ],
            "criteria": ["must preserve uncertainty"],
        },
    ]
    if dataset_type == "sft":
        for row in rows:
            row.pop("input", None)
            row.pop("reference", None)
            row.pop("criteria", None)
            row["messages"] = [{"role": "user", "content": "Answer the source question."}]
            row["target"] = "The reviewed answer."
    elif dataset_type == "preference":
        for row in rows:
            row.pop("input", None)
            row.pop("reference", None)
            row.pop("criteria", None)
            row["prompt"] = [{"role": "user", "content": "Answer the source question."}]
            row["chosen"] = "The reviewed answer."
            row["rejected"] = "The original answer."

    encoded = "".join(
        json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode("utf-8")
    lineage = [
        {
            "case_id": f"case-{index + 1}",
            "split": row["split"],
            "source_refs": [f"source-{index + 1}"],
            "paper_families": {f"family-{index + 1}": f"family-{index + 1}"},
            "paper_family_keys": [f"family-{index + 1}"],
            "session_tree_id": f"tree-{index + 1}",
            "record_type": dataset_type,
            "row_digest": _digest(row),
        }
        for index, row in enumerate(rows)
    ]
    provenance = {
        "schema_version": "feedback-dataset-provenance.v1",
        "collection_id": "collection-1",
        "dataset_type": dataset_type,
        "paper_families": {f"paper-{index + 1}": f"family-{index + 1}" for index in range(len(rows))},
        "items": lineage,
    }
    provenance_digest = _digest(provenance)
    exclusions: list[dict] = []
    digest_basis = {
        "schema_version": "feedback-dataset.v2",
        "owner_id": "user-1",
        "collection_id": "collection-1",
        "dataset_type": dataset_type,
        "rows": rows,
        "exclusions": exclusions,
        "provenance_digest": provenance_digest,
    }
    manifest_digest = _digest(digest_basis)
    manifest = {
        **digest_basis,
        "dataset_id": "dataset-1",
        "row_count": len(rows),
        "excluded_count": 0,
        "empty": False,
        "manifest_digest": manifest_digest,
        "content_digest": hashlib.sha256(encoded).hexdigest(),
        "created_at": "2026-09-24T00:00:00+00:00",
    }
    return {
        "dataset_id": "dataset-1",
        "owner_id": "user-1",
        "collection_id": "collection-1",
        "dataset_type": dataset_type,
        "rows": rows,
        "exclusions": exclusions,
        "provenance": provenance,
        "manifest": manifest,
        "manifest_digest": manifest_digest,
        "provenance_digest": provenance_digest,
        "content_digest": manifest["content_digest"],
    }


def _refresh_snapshot_digests(snapshot: dict) -> None:
    provenance = snapshot["provenance"]
    provenance_digest = _digest(provenance)
    snapshot["provenance_digest"] = provenance_digest
    digest_basis = {
        "schema_version": snapshot["manifest"]["schema_version"],
        "owner_id": snapshot["owner_id"],
        "collection_id": snapshot["collection_id"],
        "dataset_type": snapshot["dataset_type"],
        "rows": snapshot["rows"],
        "exclusions": snapshot["exclusions"],
        "provenance_digest": provenance_digest,
    }
    manifest_digest = _digest(digest_basis)
    snapshot["manifest_digest"] = manifest_digest
    snapshot["manifest"].update(
        {
            **digest_basis,
            "manifest_digest": manifest_digest,
            "provenance_digest": provenance_digest,
        }
    )


def _eval_row_id(prepared_dir: Path) -> str:
    line = (prepared_dir / "eval.jsonl").read_text(encoding="utf-8").splitlines()[0]
    return str(json.loads(line)["row_id"])


def test_prepare_materializes_split_files_and_loss_mask(tmp_path, prepare_module):
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot(dataset_type="sft")), encoding="utf-8")

    result = prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=output_dir,
        revision="abc123",
        seed=7,
    )

    assert result["status"] == "ready"
    assert result["snapshot"]["manifest_digest"] == _snapshot(dataset_type="sft")["manifest_digest"]
    assert result["counts"] == {"train": 1, "eval": 1}
    train_row = json.loads((output_dir / "train.jsonl").read_text(encoding="utf-8"))
    assert train_row["loss_mask"]
    assert len(train_row["loss_mask"]) == len(train_row["tokens"])
    assert 0 in train_row["loss_mask"]
    assert 1 in train_row["loss_mask"]
    assert json.loads((output_dir / "prepared.json").read_text(encoding="utf-8"))["revision"] == "abc123"


def test_prepare_generates_private_row_ids_for_clean_snapshot_rows(tmp_path, prepare_module):
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "prepared"
    snapshot = _snapshot(dataset_type="sft")
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=output_dir,
        revision="abc123",
        seed=7,
    )

    public_row = json.loads((output_dir / "snapshot.json").read_text(encoding="utf-8"))["rows"][0]
    prepared_row = json.loads((output_dir / "train.jsonl").read_text(encoding="utf-8"))
    assert "row_id" not in public_row
    assert "case_id" not in public_row
    assert "source_refs" not in public_row
    assert prepared_row["row_id"].startswith("row_")
    assert prepared_row["evidence"][0]["document_title"] == "Paper A"


def test_prepare_rejects_internal_identity_in_public_row(tmp_path, prepare_module):
    rows = _snapshot()["rows"]
    rows[0]["source_refs"] = ["source-leak"]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot(rows=rows)), encoding="utf-8")

    with pytest.raises(prepare_module.SnapshotValidationError, match="row_internal_field:source_refs"):
        prepare_module.prepare_snapshot(
            snapshot_path=snapshot_path,
            output_dir=tmp_path / "prepared",
            revision="abc123",
            seed=7,
        )


def test_prepare_rejects_cross_split_session_tree_leakage(tmp_path, prepare_module):
    snapshot = _snapshot()
    snapshot["provenance"]["items"][1]["session_tree_id"] = snapshot["provenance"]["items"][0][
        "session_tree_id"
    ]
    _refresh_snapshot_digests(snapshot)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(prepare_module.SnapshotValidationError, match="split_leakage"):
        prepare_module.prepare_snapshot(
            snapshot_path=snapshot_path,
            output_dir=tmp_path / "prepared",
            revision="abc123",
            seed=7,
        )


def test_prepare_rejects_context_overflow_without_truncation(tmp_path, prepare_module):
    rows = _snapshot()["rows"]
    rows[0]["input"] = "word " * 20
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot(rows=rows)), encoding="utf-8")

    with pytest.raises(prepare_module.SnapshotValidationError, match="context_overflow"):
        prepare_module.prepare_snapshot(
            snapshot_path=snapshot_path,
            output_dir=tmp_path / "prepared",
            revision="abc123",
            seed=7,
            max_input_tokens=5,
        )


def test_experiment_records_not_run_without_prediction_artifact(tmp_path, prepare_module, experiment_module):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=prepared_dir,
        revision="abc123",
        seed=7,
    )

    report = experiment_module.run_experiment(
        prepared_dir=prepared_dir,
        output_path=tmp_path / "report.json",
    )

    assert report["status"] == "not_run"
    assert report["baseline"]["status"] == "not_run"
    assert report["experiment"]["status"] == "not_run"
    assert report["protocol"]["snapshot_manifest_digest"]
    assert report["protocol"]["prepared_digest"]
    assert report["run_manifest"]["status"] == "not_run"
    assert report["run_manifest"]["artifacts"]["baseline_predictions"]["status"] == "missing"
    assert report["deployment"]["status"] == "not_run"


def test_experiment_keeps_partial_prediction_run_not_run(
    tmp_path, prepare_module, experiment_module
):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=prepared_dir,
        revision="abc123",
        seed=7,
    )
    eval_row_id = _eval_row_id(prepared_dir)
    baseline = tmp_path / "baseline.jsonl"
    baseline.write_text(
        json.dumps(
            {"row_id": eval_row_id, "prediction": "Source B reports a lower value."}
        )
        + "\n",
        encoding="utf-8",
    )

    report = experiment_module.run_experiment(
        prepared_dir=prepared_dir,
        output_path=tmp_path / "report.json",
        baseline_predictions=baseline,
    )

    assert report["status"] == "not_run"
    assert report["baseline"]["status"] == "completed"
    assert report["experiment"]["status"] == "not_run"
    assert report["comparison"]["status"] == "not_run"


def test_experiment_compares_predictions_on_same_eval_rows(
    tmp_path, prepare_module, experiment_module
):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=prepared_dir,
        revision="abc123",
        seed=7,
    )
    eval_row_id = _eval_row_id(prepared_dir)
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    baseline.write_text(
        json.dumps({"row_id": eval_row_id, "prediction": "Source B reports a lower value."}) + "\n",
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps({"row_id": eval_row_id, "prediction": "wrong"}) + "\n",
        encoding="utf-8",
    )

    report = experiment_module.run_experiment(
        prepared_dir=prepared_dir,
        output_path=tmp_path / "report.json",
        baseline_predictions=baseline,
        experiment_predictions=candidate,
    )

    assert report["status"] == "completed"
    assert report["baseline"]["metrics"]["exact_match"] == 1.0
    assert report["experiment"]["metrics"]["exact_match"] == 0.0
    assert report["comparison"]["exact_match_delta"] == -1.0


def test_experiment_run_manifest_is_deterministic_and_records_input_artifacts(
    tmp_path, prepare_module, experiment_module
):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=prepared_dir,
        revision="abc123",
        seed=7,
    )
    eval_row_id = _eval_row_id(prepared_dir)
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    baseline.write_text(
        json.dumps({"row_id": eval_row_id, "prediction": "Source B reports a lower value."}) + "\n",
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps({"row_id": eval_row_id, "prediction": "wrong"}) + "\n",
        encoding="utf-8",
    )

    first = experiment_module.run_experiment(
        prepared_dir=prepared_dir,
        output_path=tmp_path / "first.json",
        baseline_predictions=baseline,
        experiment_predictions=candidate,
    )
    second = experiment_module.run_experiment(
        prepared_dir=prepared_dir,
        output_path=tmp_path / "second.json",
        baseline_predictions=baseline,
        experiment_predictions=candidate,
    )

    manifest = first["run_manifest"]
    assert first["run_manifest"]["run_id"] == second["run_manifest"]["run_id"]
    assert manifest["prepared_digest"] == first["protocol"]["prepared_digest"]
    assert manifest["comparison_status"] == "completed"
    baseline_artifact = manifest["artifacts"]["baseline_predictions"]
    assert baseline_artifact["status"] == "provided"
    assert baseline_artifact["sha256"] == hashlib.sha256(baseline.read_bytes()).hexdigest()
    assert baseline_artifact["byte_size"] == baseline.stat().st_size
    assert baseline_artifact["line_count"] == 1
    assert "path" not in baseline_artifact


def test_experiment_run_id_changes_when_prediction_bytes_change(
    tmp_path, prepare_module, experiment_module
):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=prepared_dir,
        revision="abc123",
        seed=7,
    )
    eval_row_id = _eval_row_id(prepared_dir)
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    baseline.write_text(
        json.dumps({"row_id": eval_row_id, "prediction": "Source B reports a lower value."}) + "\n",
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps({"row_id": eval_row_id, "prediction": "wrong"}) + "\n",
        encoding="utf-8",
    )
    first = experiment_module.run_experiment(
        prepared_dir=prepared_dir,
        output_path=tmp_path / "first.json",
        baseline_predictions=baseline,
        experiment_predictions=candidate,
    )
    candidate.write_text(
        json.dumps({"row_id": eval_row_id, "prediction": "a different wrong answer"}) + "\n",
        encoding="utf-8",
    )
    second = experiment_module.run_experiment(
        prepared_dir=prepared_dir,
        output_path=tmp_path / "second.json",
        baseline_predictions=baseline,
        experiment_predictions=candidate,
    )

    assert first["run_manifest"]["run_id"] != second["run_manifest"]["run_id"]
    assert first["run_manifest"]["artifacts"]["experiment_predictions"]["sha256"] != second[
        "run_manifest"
    ]["artifacts"]["experiment_predictions"]["sha256"]


def test_experiment_records_weight_manifest_as_validated_metadata(
    tmp_path, prepare_module, experiment_module
):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot = _snapshot()
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=prepared_dir,
        revision="abc123",
        seed=7,
    )
    weights = tmp_path / "weights.json"
    weights.write_text(
        json.dumps(
            {
                "model_id": "candidate-1",
                "snapshot_manifest_digest": snapshot["manifest_digest"],
                "revision": "abc123",
                "seed": 7,
            }
        ),
        encoding="utf-8",
    )

    report = experiment_module.run_experiment(
        prepared_dir=prepared_dir,
        output_path=tmp_path / "report.json",
        weights_manifest=weights,
    )

    assert report["weights"]["status"] == "validated"
    assert report["weights"]["artifact"]["status"] == "provided"
    assert report["weights"]["artifact"]["sha256"] == hashlib.sha256(
        weights.read_bytes()
    ).hexdigest()
    assert report["run_manifest"]["artifacts"]["weights_manifest"]["byte_size"] == weights.stat().st_size
    assert report["deployment"]["status"] == "not_run"
    assert report["status"] == "not_run"


def test_evaluation_without_reference_is_reported_as_unscorable(experiment_module):
    rows = [{"row_id": "row-1", "reference": None}]
    metrics = experiment_module._metrics(
        rows,
        {"row-1": {"prediction": ""}},
        dataset_type="evaluation",
    )

    assert metrics["evaluated"] == 1
    assert metrics["scoreable"] == 0
    assert metrics["reference_missing"] == 1
    assert metrics["exact_match"] is None


def test_experiment_rejects_prediction_set_that_changes_eval_rows(
    tmp_path, prepare_module, experiment_module
):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=prepared_dir,
        revision="abc123",
        seed=7,
    )
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({"row_id": "unknown", "prediction": "x"}) + "\n", encoding="utf-8")

    with pytest.raises(experiment_module.ExperimentProtocolError, match="eval_row_ids"):
        experiment_module.run_experiment(
            prepared_dir=prepared_dir,
            output_path=tmp_path / "report.json",
            baseline_predictions=predictions,
        )


def test_experiment_rejects_weight_manifest_from_different_snapshot(
    tmp_path, prepare_module, experiment_module
):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot = _snapshot()
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=prepared_dir,
        revision="abc123",
        seed=7,
    )
    weight_manifest = tmp_path / "weights.json"
    weight_manifest.write_text(
        json.dumps(
            {
                "snapshot_manifest_digest": "0" * 64,
                "revision": "abc123",
                "seed": 7,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(experiment_module.ExperimentProtocolError, match="weight_snapshot_digest"):
        experiment_module.run_experiment(
            prepared_dir=prepared_dir,
            output_path=tmp_path / "report.json",
            weights_manifest=weight_manifest,
        )


def test_experiment_rechecks_snapshot_before_consuming_prepared_rows(
    tmp_path, prepare_module, experiment_module
):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=prepared_dir,
        revision="abc123",
        seed=7,
    )
    tampered = json.loads((prepared_dir / "snapshot.json").read_text(encoding="utf-8"))
    tampered["rows"][1]["input"] = "tampered"
    (prepared_dir / "snapshot.json").write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(experiment_module.ExperimentProtocolError, match="mismatch"):
        experiment_module.run_experiment(
            prepared_dir=prepared_dir,
            output_path=tmp_path / "report.json",
        )


def test_experiment_rejects_prepared_metadata_tampering(
    tmp_path, prepare_module, experiment_module
):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prepare_module.prepare_snapshot(
        snapshot_path=snapshot_path,
        output_dir=prepared_dir,
        revision="abc123",
        seed=7,
    )
    prepared = json.loads((prepared_dir / "prepared.json").read_text(encoding="utf-8"))
    prepared["revision"] = "attacker-revision"
    (prepared_dir / "prepared.json").write_text(
        json.dumps(prepared), encoding="utf-8"
    )

    with pytest.raises(experiment_module.ExperimentProtocolError, match="prepared_digest"):
        experiment_module.run_experiment(
            prepared_dir=prepared_dir,
            output_path=tmp_path / "report.json",
        )


def test_cli_prepare_to_experiment_round_trip(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    prepared = _run_cli(
        "prepare.py",
        snapshot_path,
        prepared_dir,
        "--revision",
        "cli-revision",
        "--seed",
        13,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(prepared.stdout)["status"] == "ready"
    eval_row_id = _eval_row_id(prepared_dir)

    not_run_report = tmp_path / "not-run.json"
    not_run = _run_cli("experiment.py", prepared_dir, not_run_report)
    assert not_run.returncode == 0, not_run.stderr
    assert json.loads(not_run.stdout)["status"] == "not_run"
    assert json.loads(not_run_report.read_text(encoding="utf-8"))["status"] == "not_run"

    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    baseline.write_text(
        json.dumps({"row_id": eval_row_id, "prediction": "Source B reports a lower value."})
        + "\n",
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps({"row_id": eval_row_id, "prediction": "wrong"}) + "\n",
        encoding="utf-8",
    )
    complete_report = tmp_path / "complete.json"
    complete = _run_cli(
        "experiment.py",
        prepared_dir,
        complete_report,
        "--baseline-predictions",
        baseline,
        "--experiment-predictions",
        candidate,
    )
    assert complete.returncode == 0, complete.stderr
    report = json.loads(complete.stdout)
    assert report["status"] == "completed"
    assert report["comparison"]["exact_match_delta"] == -1.0
    assert report["run_manifest"]["run_id"]
    persisted = json.loads(complete_report.read_text(encoding="utf-8"))
    assert persisted["status"] == "completed"
    assert persisted["run_manifest"]["run_id"] == report["run_manifest"]["run_id"]


def test_cli_rejects_lineage_and_prepared_metadata_tampering(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prepared = _run_cli("prepare.py", snapshot_path, prepared_dir, "--revision", "cli-revision")
    assert prepared.returncode == 0, prepared.stderr

    stored_snapshot = json.loads((prepared_dir / "snapshot.json").read_text(encoding="utf-8"))
    stored_snapshot["provenance"]["items"][0]["source_refs"] = ["tampered-source"]
    (prepared_dir / "snapshot.json").write_text(
        json.dumps(stored_snapshot), encoding="utf-8"
    )
    lineage_check = _run_cli("experiment.py", prepared_dir, tmp_path / "lineage.json")
    assert lineage_check.returncode != 0
    assert "provenance_digest_mismatch" in lineage_check.stderr

    # Recreate a clean directory so the prepared metadata check is isolated
    # from the previous snapshot corruption.
    prepared = _run_cli("prepare.py", snapshot_path, prepared_dir, "--revision", "cli-revision")
    assert prepared.returncode == 0, prepared.stderr
    prepared_metadata = json.loads((prepared_dir / "prepared.json").read_text(encoding="utf-8"))
    prepared_metadata["revision"] = "tampered-revision"
    (prepared_dir / "prepared.json").write_text(
        json.dumps(prepared_metadata), encoding="utf-8"
    )
    metadata_check = _run_cli("experiment.py", prepared_dir, tmp_path / "metadata.json")
    assert metadata_check.returncode != 0
    assert "prepared_digest_mismatch" in metadata_check.stderr


def test_cli_rejects_prediction_rows_outside_frozen_eval_set(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    prepared_dir = tmp_path / "prepared"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prepared = _run_cli("prepare.py", snapshot_path, prepared_dir, "--revision", "cli-revision")
    assert prepared.returncode == 0, prepared.stderr
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        json.dumps({"row_id": "unknown", "prediction": "x"}) + "\n",
        encoding="utf-8",
    )

    result = _run_cli(
        "experiment.py",
        prepared_dir,
        tmp_path / "report.json",
        "--baseline-predictions",
        predictions,
    )
    assert result.returncode != 0
    assert "eval_row_ids_mismatch" in result.stderr
