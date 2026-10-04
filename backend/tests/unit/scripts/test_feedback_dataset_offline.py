from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


def _load_module(name: str, relative_path: str):
    backend_root = Path(__file__).resolve().parents[3]
    script_path = backend_root / "scripts" / "evaluation" / "feedback_dataset" / relative_path
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def prepare_module():
    return _load_module("feedback_dataset_prepare_export", "prepare.py")


@pytest.fixture(scope="module")
def experiment_module():
    return _load_module("feedback_dataset_experiment_export", "experiment.py")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _jsonl_bytes(rows: list[dict]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )


def _rows(dataset_type: str = "evaluation") -> list[dict]:
    values = [
        ("Paper A", "Source A supports the claim.", "tree-a"),
        ("Paper B", "Source B reports a lower value.", "tree-b"),
    ]
    result: list[dict] = []
    for title, quote, _tree in values:
        base = {
            "messages": [{"role": "user", "content": f"文献：{title}\n原文：{quote}\n\n问题：核对来源中的结论。"}],
        }
        if dataset_type == "sft":
            base["messages"] = [
                *base["messages"],
                {"role": "assistant", "content": quote},
            ]
        elif dataset_type == "preference":
            base["prompt"] = base.pop("messages")
            base.update({
                "chosen": [{"role": "assistant", "content": "基于来源的回答。"}],
                "rejected": [{"role": "assistant", "content": "没有依据的回答。"}],
            })
        else:
            base.update(
                {
                    "reference": quote,
                    "criteria": ["必须保留来源边界"],
                    "evaluation_mode": "reference",
                }
            )
        result.append(base)
    return result


def _bundle(tmp_path: Path, *, dataset_type: str = "evaluation") -> tuple[Path, dict]:
    rows = _rows(dataset_type)
    provenance = []
    for index, row in enumerate(rows, start=1):
        provenance.append(
            {
                "schema_version": "feedback-dataset-provenance.v1",
                "row_key": hashlib.sha256(f"sample-{index}:revision-{index}".encode()).hexdigest(),
                "row_digest": _digest(row),
                "sample_id": f"sample-{index}",
                "source_case_id": f"case-{index}",
                "revision_id": f"revision-{index}",
                "document_ids": [f"document-{index}"],
                "session_tree_id": "tree-a" if index == 1 else "tree-b",
                "source_refs": [f"source-{index}"],
                "evidence_records": [{"document_id": f"document-{index}", "quote": "原文"}],
            }
        )
    manifest = {
        "manifest_schema_version": "feedback-dataset-export-manifest.v1",
        "schema_version": {
            "sft": "literature-sft.v2",
            "preference": "literature-preference.v2",
            "evaluation": "literature-evaluation.v2",
        }[dataset_type],
        "dataset_type": dataset_type,
        "dataset_id": "dataset-1",
        "collection_id": "collection-1",
        "export_id": "export-1",
        "export_no": 1,
        "row_count": len(rows),
        "main_file": "data.jsonl",
        "provenance_file": "provenance.jsonl",
        "member_digest": "a" * 64,
        "preview_digest": "b" * 64,
        "content_digest": hashlib.sha256(_jsonl_bytes(rows)).hexdigest(),
        "provenance_digest": _digest(provenance),
        "created_at": "2026-09-29T00:00:00+00:00",
    }
    manifest["manifest_digest"] = _digest(manifest)
    source = tmp_path / "export"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "data.jsonl").write_bytes(_jsonl_bytes(rows))
    (source / "provenance.jsonl").write_bytes(_jsonl_bytes(provenance))
    return source, manifest


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


def _eval_row_id(prepared_dir: Path) -> str:
    return json.loads((prepared_dir / "eval.jsonl").read_text(encoding="utf-8").splitlines()[0])["row_id"]


def _eval_rows(prepared_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (prepared_dir / "eval.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_export_cli_defaults_to_evaluation_and_keeps_sidecars_private(tmp_path, prepare_module):
    source, manifest = _bundle(tmp_path)
    output = tmp_path / "prepared"
    result = _run_cli("prepare.py", source, output, "--revision", "test-revision")
    assert result.returncode == 0, result.stderr
    prepared = prepare_module.load_prepared(output)
    assert prepared["counts"] == {"train": 0, "eval": 2}
    assert prepared["experiment_mode"] == "evaluation_only"
    assert prepared["export"]["export_id"] == "export-1"
    assert json.loads((output / "export-manifest.json").read_text()) == manifest
    row = json.loads((output / "eval.jsonl").read_text().splitlines()[0])
    assert row["row_id"].startswith("row_")
    assert "source_refs" not in row
    assert "document_id" not in json.dumps(row, ensure_ascii=False)


def test_train_eval_plan_uses_export_digest_and_checks_source_isolation(tmp_path, prepare_module):
    source, manifest = _bundle(tmp_path)
    rows = [json.loads(line) for line in (source / "data.jsonl").read_text().splitlines()]
    plan = {
        "schema_version": "feedback-experiment-plan.v2",
        "export_manifest_digest": manifest["manifest_digest"],
        "mode": "train_eval",
        "rows": [
            {
                "row_digest": _digest(rows[0]),
                "split": "train",
                "input_document_ids": ["document-1"],
                "source_review_reason": "核对完整输入来源。",
            },
            {
                "row_digest": _digest(rows[1]),
                "split": "eval",
                "input_document_ids": ["document-2"],
                "source_review_reason": "核对版本身份。",
            },
        ],
        "document_groups": {"document-1": "paper-a", "document-2": "paper-b"},
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    prepared = prepare_module.prepare_export(
        export_path=source,
        output_dir=tmp_path / "prepared",
        experiment_plan_path=plan_path,
    )
    assert prepared["counts"] == {"train": 1, "eval": 1}

    plan["document_groups"]["document-2"] = "paper-a"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(prepare_module.SnapshotValidationError, match="split_leakage"):
        prepare_module.prepare_export(
            export_path=source,
            output_dir=tmp_path / "leaking",
            experiment_plan_path=plan_path,
        )


def test_legacy_snapshot_is_rejected_at_offline_boundary(tmp_path, prepare_module):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"dataset_id": "old", "rows": [], "manifest": {}}), encoding="utf-8")
    with pytest.raises(prepare_module.SnapshotValidationError, match="export_manifest_schema_invalid"):
        prepare_module.prepare_snapshot(snapshot_path=legacy, output_dir=tmp_path / "prepared")


def test_tampering_data_or_provenance_is_rejected(tmp_path, prepare_module):
    source, _manifest = _bundle(tmp_path)
    (source / "data.jsonl").write_text(
        (source / "data.jsonl").read_text(encoding="utf-8").replace("Source A", "Tampered", 1),
        encoding="utf-8",
    )
    with pytest.raises(prepare_module.SnapshotValidationError, match="export_content_digest_mismatch"):
        prepare_module.prepare_export(export_path=source, output_dir=tmp_path / "prepared")


def test_sft_export_derives_target_and_loss_mask(tmp_path, prepare_module):
    source, _manifest = _bundle(tmp_path, dataset_type="sft")
    output = tmp_path / "prepared"
    prepare_module.prepare_export(export_path=source, output_dir=output, revision="r1")
    row = json.loads((output / "eval.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["target"] == "Source A supports the claim."
    assert len(row["loss_mask"]) == len(row["tokens"])
    assert 0 in row["loss_mask"] and 1 in row["loss_mask"]
    assert any(
        token == "Source" and mask == 0
        for token, mask in zip(row["tokens"], row["loss_mask"], strict=True)
    )


@pytest.mark.parametrize("task_type", ["sft", "preference", "evaluation"])
def test_v2_rejects_legacy_main_fields(prepare_module, task_type):
    row = {**_rows(task_type)[0], "context": [{"document_title": "Paper", "text": "excerpt"}]}
    with pytest.raises(prepare_module.SnapshotValidationError, match="row_fields_invalid"):
        prepare_module._validate_row_shape(row, dataset_type=task_type, row_id="row-1", max_input_tokens=4096)


@pytest.mark.parametrize("completion", ["answer", [], [{"role": "user", "content": "answer"}], [{"role": "assistant", "content": ""}]])
def test_preference_requires_assistant_completions(prepare_module, completion):
    row = {**_rows("preference")[0], "chosen": completion}
    with pytest.raises(prepare_module.SnapshotValidationError):
        prepare_module._validate_row_shape(row, dataset_type="preference", row_id="row-1", max_input_tokens=4096)


def test_v1_export_requires_republication_for_offline_preparation(tmp_path, prepare_module):
    source, manifest = _bundle(tmp_path)
    manifest["schema_version"] = "literature-evaluation.v1"
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = _digest(manifest)
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(prepare_module.SnapshotValidationError, match="export_task_schema_invalid"):
        prepare_module.prepare_export(export_path=source, output_dir=tmp_path / "prepared")


def test_experiment_compares_predictions_against_same_export_eval_set(tmp_path, prepare_module, experiment_module):
    source, manifest = _bundle(tmp_path, dataset_type="sft")
    prepared_dir = tmp_path / "prepared"
    prepare_module.prepare_export(export_path=source, output_dir=prepared_dir, revision="abc123", seed=7)
    eval_rows = _eval_rows(prepared_dir)
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    baseline.write_text(
        "".join(json.dumps({"row_id": row["row_id"], "prediction": row["target"]}) + "\n" for row in eval_rows)
    )
    candidate.write_text(
        "".join(json.dumps({"row_id": row["row_id"], "prediction": "wrong"}) + "\n" for row in eval_rows)
    )
    report = experiment_module.run_experiment(
        prepared_dir=prepared_dir,
        output_path=tmp_path / "report.json",
        baseline_predictions=baseline,
        experiment_predictions=candidate,
    )
    assert report["status"] == "completed"
    assert report["protocol"]["export_id"] == "export-1"
    assert report["run_manifest"]["export_manifest_digest"] == manifest["manifest_digest"]
    assert report["baseline"]["metrics"]["exact_match"] == 1.0
    assert report["experiment"]["metrics"]["exact_match"] == 0.0


def test_experiment_requires_new_export_digest_in_weight_manifest(tmp_path, prepare_module, experiment_module):
    source, manifest = _bundle(tmp_path)
    prepared_dir = tmp_path / "prepared"
    prepare_module.prepare_export(export_path=source, output_dir=prepared_dir, revision="abc123", seed=7)
    weights = tmp_path / "weights.json"
    weights.write_text(
        json.dumps({
            "model_id": "candidate-1",
            "export_manifest_digest": manifest["manifest_digest"],
            "revision": "abc123",
            "seed": 7,
        }),
        encoding="utf-8",
    )
    report = experiment_module.run_experiment(
        prepared_dir=prepared_dir,
        output_path=tmp_path / "report.json",
        weights_manifest=weights,
    )
    assert report["weights"]["status"] == "validated"
