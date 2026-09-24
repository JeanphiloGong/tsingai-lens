from __future__ import annotations

import hashlib
import importlib.util
import json
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


def _snapshot(*, dataset_type: str = "evaluation", rows: list[dict] | None = None) -> dict:
    rows = rows or [
        {
            "row_id": "row-1",
            "case_id": "case-1",
            "split": "train",
            "record_type": dataset_type,
            "input": "Which source supports the claim?",
            "reference": "Source A supports the claim.",
            "evidence": ["source-a"],
            "criteria": ["must cite source"],
            "source_refs": ["source-a"],
            "paper_family_keys": ["family-a"],
            "session_tree_id": "tree-a",
        },
        {
            "row_id": "row-2",
            "case_id": "case-2",
            "split": "eval",
            "record_type": dataset_type,
            "input": "What did source B report?",
            "reference": "Source B reports a lower value.",
            "evidence": ["source-b"],
            "criteria": ["must preserve uncertainty"],
            "source_refs": ["source-b"],
            "paper_family_keys": ["family-b"],
            "session_tree_id": "tree-b",
        },
    ]
    if dataset_type == "sft":
        for row in rows:
            row.pop("input", None)
            row.pop("reference", None)
            row.pop("evidence", None)
            row.pop("criteria", None)
            row["messages"] = [{"role": "user", "content": "Answer the source question."}]
            row["target"] = "The reviewed answer."
    elif dataset_type == "preference":
        for row in rows:
            row.pop("input", None)
            row.pop("reference", None)
            row.pop("evidence", None)
            row.pop("criteria", None)
            row["prompt"] = [{"role": "user", "content": "Answer the source question."}]
            row["chosen"] = "The reviewed answer."
            row["rejected"] = "The original answer."
    for row in rows:
        basis = dict(row)
        basis.pop("content_digest", None)
        basis.pop("row_id", None)
        row["content_digest"] = _digest(basis)
    encoded = "".join(
        json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode("utf-8")
    provenance = {
        "schema_version": "feedback-dataset-provenance.v1",
        "collection_id": "collection-1",
        "dataset_type": dataset_type,
        "paper_families": {"paper-a": "family-a", "paper-b": "family-b"},
        "items": [
            {
                "case_id": row["case_id"],
                "split": row["split"],
                "source_refs": row["source_refs"],
                "paper_families": {
                    row["paper_family_keys"][0]: row["paper_family_keys"][0]
                },
                "session_tree_id": row["session_tree_id"],
            }
            for row in rows
        ],
    }
    provenance_digest = _digest(provenance)
    exclusions: list[dict] = []
    digest_basis = {
        "schema_version": "feedback-dataset.v1",
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


def test_prepare_rejects_cross_split_session_tree_leakage(tmp_path, prepare_module):
    rows = _snapshot()["rows"]
    rows[1]["session_tree_id"] = rows[0]["session_tree_id"]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot(rows=rows)), encoding="utf-8")

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
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    baseline.write_text(
        json.dumps({"row_id": "row-2", "prediction": "Source B reports a lower value."}) + "\n",
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps({"row_id": "row-2", "prediction": "wrong"}) + "\n",
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
