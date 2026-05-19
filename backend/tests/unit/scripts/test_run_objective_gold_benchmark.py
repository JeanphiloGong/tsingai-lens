from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_benchmark_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "run_objective_gold_benchmark.py"
    )
    spec = importlib.util.spec_from_file_location(
        "run_objective_gold_benchmark",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_objective_quality_gate_passes_required_paper_thresholds():
    benchmark = _load_benchmark_module()

    gate = benchmark.evaluate_objective_quality_gate(
        {
            "papers": [
                _paper(
                    "P001",
                    measurement_recall=1.0,
                    comparison_recall=1.0,
                    comparison_precision=1.0,
                    prediction_core_measurement_count=80,
                ),
                _paper(
                    "P002",
                    measurement_recall=0.5,
                    comparison_recall=0.0,
                    comparison_precision=None,
                    prediction_core_measurement_count=6,
                ),
                _paper(
                    "P005",
                    measurement_recall=1.0,
                    comparison_recall=0.2,
                    comparison_precision=0.25,
                    prediction_core_measurement_count=4,
                ),
            ]
        }
    )

    assert gate["status"] == "pass"
    assert gate["failed_checks"] == []


def test_objective_quality_gate_reports_failed_thresholds():
    benchmark = _load_benchmark_module()

    gate = benchmark.evaluate_objective_quality_gate(
        {
            "papers": [
                _paper(
                    "P001",
                    measurement_recall=1.0,
                    comparison_recall=0.6842,
                    comparison_precision=0.1912,
                    prediction_core_measurement_count=80,
                ),
                _paper(
                    "P002",
                    measurement_recall=0.0,
                    comparison_recall=0.0,
                    comparison_precision=None,
                    prediction_core_measurement_count=0,
                ),
            ]
        }
    )

    assert gate["status"] == "fail"
    assert {
        (check["paper_id"], check["metric"])
        for check in gate["failed_checks"]
    } == {
        ("P001", "comparison_recall"),
        ("P001", "comparison_precision"),
        ("P002", "measurement_recall"),
        ("P002", "prediction_core_measurement_count"),
        ("P005", "paper_present"),
    }


def test_objective_benchmark_generates_research_objective_target_report(
    tmp_path,
    monkeypatch,
):
    benchmark = _load_benchmark_module()

    def fake_convert_expert_gold(*, input_dir, output_path):
        output_path.write_text('{"papers": []}', encoding="utf-8")
        return output_path

    def fake_export_prediction_bundle(
        *,
        backend_root,
        collection_id,
        source_output_dir,
        output_path,
        fact_source,
    ):
        assert fact_source == "objective_first"
        output_path.write_text('{"papers": []}', encoding="utf-8")
        return output_path

    def fake_evaluate_gold_vs_prediction(
        *,
        gold_path,
        prediction_path,
        output_path,
        gold_paper_ids,
    ):
        output_path.write_text(
            json.dumps({"summary": {"paper_count": 1}, "papers": []}),
            encoding="utf-8",
        )
        return output_path

    def fake_build_research_objective_target_prediction(
        *,
        prediction_bundle_path,
        output_path,
        report_path,
    ):
        assert prediction_bundle_path == tmp_path / "objective_prediction_bundle.json"
        output_path.write_text('{"evidence_scope": {}}', encoding="utf-8")
        report_path.write_text(
            json.dumps({"quality_gate": {"status": "fail"}}),
            encoding="utf-8",
        )
        return output_path

    monkeypatch.setattr(
        benchmark.convert_expert_gold,
        "convert_expert_gold",
        fake_convert_expert_gold,
    )
    monkeypatch.setattr(
        benchmark.export_prediction_bundle,
        "export_prediction_bundle",
        fake_export_prediction_bundle,
    )
    monkeypatch.setattr(
        benchmark.evaluate_gold_vs_prediction,
        "evaluate_gold_vs_prediction",
        fake_evaluate_gold_vs_prediction,
    )
    monkeypatch.setattr(
        benchmark.build_research_objective_target_prediction,
        "build_research_objective_target_prediction",
        fake_build_research_objective_target_prediction,
    )

    summary = benchmark.run_objective_gold_benchmark(
        backend_root=tmp_path,
        collection_id="col_test",
        gold_input_dir=tmp_path / "gold",
        benchmark_output_dir=tmp_path,
    )

    assert summary["prediction_bundle"] == str(
        tmp_path / "objective_prediction_bundle.json"
    )
    assert summary["research_objective_target_prediction"] == str(
        tmp_path / "research_objective_target_prediction.json"
    )
    assert summary["research_objective_target_report"] == str(
        tmp_path / "research_objective_target_report.json"
    )
    assert summary["research_objective_target"] == {
        "quality_gate": {"status": "fail"}
    }


def test_objective_benchmark_reports_duplicate_prediction_mappings():
    benchmark = _load_benchmark_module()

    quality = benchmark.evaluate_paper_mapping_quality(
        [
            {
                "gold_paper_id": "P001",
                "prediction_paper_id": "prediction-a",
                "paper_mapping": {"status": "mapped"},
            },
            {
                "gold_paper_id": "P002",
                "prediction_paper_id": "prediction-a",
                "paper_mapping": {"status": "mapped"},
            },
            {
                "gold_paper_id": "P003",
                "prediction_paper_id": "prediction-b",
                "paper_mapping": {"status": "mapped"},
            },
        ]
    )

    assert quality == {
        "status": "fail",
        "mapped_paper_count": 3,
        "unique_prediction_paper_count": 2,
        "duplicate_prediction_mappings": [
            {
                "prediction_paper_id": "prediction-a",
                "gold_paper_ids": ["P001", "P002"],
            }
        ],
        "unmapped_gold_paper_ids": [],
    }


def _paper(
    paper_id: str,
    *,
    measurement_recall: float,
    comparison_recall: float,
    comparison_precision: float | None,
    prediction_core_measurement_count: int,
) -> dict:
    return {
        "gold_paper_id": paper_id,
        "measurements": {
            "recall": measurement_recall,
            "prediction_core_count": prediction_core_measurement_count,
        },
        "comparisons": {
            "recall": comparison_recall,
            "precision": comparison_precision,
        },
    }
