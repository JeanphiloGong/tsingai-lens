from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_evaluator_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "evaluate_gold_vs_prediction.py"
    )
    spec = importlib.util.spec_from_file_location(
        "evaluate_gold_vs_prediction",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evaluate_gold_vs_prediction_reports_first_pass_alignment(tmp_path):
    evaluator = _load_evaluator_module()
    gold_path = tmp_path / "gold_bundle.json"
    prediction_path = tmp_path / "prediction_bundle.json"
    report_path = tmp_path / "evaluation_report.json"
    gold_path.write_text(json.dumps(_gold_bundle()), encoding="utf-8")
    prediction_path.write_text(json.dumps(_prediction_bundle()), encoding="utf-8")

    result_path = evaluator.evaluate_gold_vs_prediction(
        gold_path=gold_path,
        prediction_path=prediction_path,
        output_path=report_path,
        gold_paper_ids=["P001"],
    )

    assert result_path == report_path
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["metadata"]["schema_version"] == (
        "expert-gold-evaluation-report-v0.1"
    )
    assert report["summary"]["papers_evaluated"] == 1
    assert report["summary"]["mapped_papers"] == 1
    assert report["summary"]["sample_recall"] == 1.0
    assert report["summary"]["measurement_recall"] == 0.6667
    assert report["summary"]["measurement_precision"] == 0.5
    assert report["summary"]["comparison_recall"] == 1.0
    assert report["summary"]["comparison_precision"] == 1.0

    paper = report["papers"][0]
    assert paper["paper_mapping"]["status"] == "mapped"
    assert paper["samples"]["matched_sample_keys"] == ["1", "2"]
    assert paper["samples"]["extra_generic_prediction_samples"][0]["label"] == (
        "316L stainless steel"
    )
    assert paper["measurements"]["exact_match_count"] == 2
    assert paper["measurements"]["value_mismatch_count"] == 1
    assert paper["measurements"]["duplicate_prediction_groups"][0]["count"] == 2
    assert paper["comparisons"]["pairwise_exact_matching_status"] == "active"
    assert paper["comparisons"]["exact_match_count"] == 1
    assert paper["test_conditions"]["missing_gold_condition_families"][0][
        "family"
    ] == "hardness"
    assert paper["evidence"]["prediction_measurements_without_evidence"] == 1


def _gold_bundle() -> dict:
    return {
        "metadata": {"schema_version": "expert-gold-bundle-v0.1"},
        "papers": [
            {
                "paper_id": "P001",
                "title": "Effect of process on 316L properties",
                "doi": "10.1000/test",
                "document_type": "实验研究",
            }
        ],
        "samples": [
            {
                "paper_id": "P001",
                "sample_id": "S001",
                "label_in_paper": "Sample 1",
                "sample_description": "sample 1",
            },
            {
                "paper_id": "P001",
                "sample_id": "S002",
                "label_in_paper": "Sample 2",
                "sample_description": "sample 2",
            },
        ],
        "test_conditions": [
            {
                "paper_id": "P001",
                "test_condition_id": "T001",
                "test_type": "tensile test",
            },
            {
                "paper_id": "P001",
                "test_condition_id": "T002",
                "test_type": "microhardness test",
            },
        ],
        "measurement_results": [
            {
                "paper_id": "P001",
                "result_id": "R001",
                "sample_id": "S001",
                "metric_name": "yield strength",
                "value_or_trend": "100",
                "unit": "MPa",
                "evidence_ids": ["E001"],
            },
            {
                "paper_id": "P001",
                "result_id": "R002",
                "sample_id": "S002",
                "metric_name": "elongation",
                "value_or_trend": "10",
                "unit": "%",
                "evidence_ids": ["E002"],
            },
            {
                "paper_id": "P001",
                "result_id": "R003",
                "sample_id": "S002",
                "metric_name": "microhardness",
                "value_or_trend": "200",
                "unit": "HV",
                "evidence_ids": ["E003"],
            },
        ],
        "comparisons": [
            {
                "paper_id": "P001",
                "comparison_id": "C001",
                "current_sample_id": "S002",
                "baseline_sample_ids": ["S001"],
                "metric_name": "elongation",
                "current_value": "10",
                "baseline_value": "5",
                "unit": "%",
            }
        ],
        "observations": [],
        "evidence": [],
    }


def _prediction_bundle() -> dict:
    paper_id = "hash-paper"
    return {
        "metadata": {"schema_version": "prediction-bundle-v0.1"},
        "papers": [
            {
                "paper_id": paper_id,
                "title": "P001-Effect of process on 316L properties.pdf",
                "source_filename": "P001-Effect of process on 316L properties.pdf",
                "document_type": "experimental",
            }
        ],
        "samples": [
            {
                "paper_id": paper_id,
                "sample_id": "var-1",
                "label_in_paper": "1",
                "sample_description": "1",
                "evidence_ids": ["anchor-s1"],
            },
            {
                "paper_id": paper_id,
                "sample_id": "var-2",
                "label_in_paper": "2",
                "sample_description": "2",
                "evidence_ids": ["anchor-s2"],
            },
            {
                "paper_id": paper_id,
                "sample_id": "var-generic",
                "label_in_paper": "316L stainless steel",
                "sample_description": "316L stainless steel",
                "evidence_ids": [],
            },
        ],
        "test_conditions": [
            {
                "paper_id": paper_id,
                "test_condition_id": "tc-tensile",
                "test_type": "mechanical_properties",
                "condition_completeness": "complete",
            }
        ],
        "measurement_results": [
            {
                "paper_id": paper_id,
                "result_id": "res-yield",
                "sample_id": "var-1",
                "metric_name": "yield_strength",
                "value_payload": {"value": 100},
                "unit": "MPa",
                "evidence_ids": ["anchor-yield"],
            },
            {
                "paper_id": paper_id,
                "result_id": "res-elongation",
                "sample_id": "var-2",
                "metric_name": "elongation",
                "value_payload": {"value": 10},
                "unit": "%",
                "evidence_ids": ["anchor-elongation"],
            },
            {
                "paper_id": paper_id,
                "result_id": "res-hardness-a",
                "sample_id": "var-2",
                "metric_name": "hardness",
                "value_payload": {"value": 210},
                "unit": "HV",
                "evidence_ids": ["anchor-hardness"],
            },
            {
                "paper_id": paper_id,
                "result_id": "res-hardness-b",
                "sample_id": "var-2",
                "metric_name": "hardness",
                "value_payload": {"value": 210},
                "unit": "HV",
                "evidence_ids": [],
            },
        ],
        "comparisons": [
            {
                "paper_id": paper_id,
                "comparison_id": "cmp-elongation",
                "current_sample_id": "var-2",
                "baseline_sample_ids": ["var-1"],
                "comparison_metric": "elongation",
                "current_value": 10,
                "baseline_value": 5,
                "unit": "%",
                "evidence_ids": ["ev-elongation"],
            }
        ],
        "observations": [],
        "evidence": [{"paper_id": paper_id, "evidence_id": "anchor-yield"}],
    }
