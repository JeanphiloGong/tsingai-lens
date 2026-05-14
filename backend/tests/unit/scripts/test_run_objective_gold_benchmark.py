from __future__ import annotations

import importlib.util
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
