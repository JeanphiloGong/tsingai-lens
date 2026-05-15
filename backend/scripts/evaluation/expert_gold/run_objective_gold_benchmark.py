#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GOLD_DIR = DEFAULT_BACKEND_ROOT / "tests" / "fixtures" / "local_expert_gold"
DEFAULT_OUTPUT_DIR = DEFAULT_GOLD_DIR / "generated" / "objective_first"
DEFAULT_QUALITY_THRESHOLDS = {
    "P001": {
        "measurement_recall": 1.0,
        "comparison_recall": 0.95,
        "comparison_precision": 0.8,
    },
    "P002": {
        "measurement_recall": 0.5,
        "prediction_core_measurement_count": 1,
    },
    "P005": {
        "measurement_recall": 1.0,
    },
}

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import convert_expert_gold  # noqa: E402
import build_research_objective_target_prediction  # noqa: E402
import evaluate_gold_vs_prediction  # noqa: E402
import export_prediction_bundle  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the offline expert-gold benchmark against objective-first "
            "Core evidence units from an already-built collection."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--collection-id",
        help="Collection id under <backend-root>/data/collections/<collection-id>.",
    )
    source.add_argument(
        "--output-dir",
        type=Path,
        help="Direct collection output directory; collection id is inferred from it.",
    )
    parser.add_argument(
        "--backend-root",
        type=Path,
        default=DEFAULT_BACKEND_ROOT,
        help="Backend root. Defaults to the repo-local backend directory.",
    )
    parser.add_argument(
        "--gold-input-dir",
        type=Path,
        default=DEFAULT_GOLD_DIR,
        help="Expert CSV/PDF directory.",
    )
    parser.add_argument(
        "--benchmark-output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated benchmark bundles and reports.",
    )
    parser.add_argument(
        "--gold-paper-id",
        action="append",
        help=(
            "Evaluate one gold paper id. May be repeated. Defaults to every "
            "gold paper that can be mapped to the prediction bundle."
        ),
    )
    parser.add_argument(
        "--quality-gate",
        action="store_true",
        help=(
            "Evaluate objective-first benchmark thresholds and exit non-zero "
            "when required P001/P002/P005 checks fail."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_objective_gold_benchmark(
        backend_root=args.backend_root,
        collection_id=args.collection_id,
        source_output_dir=args.output_dir,
        gold_input_dir=args.gold_input_dir,
        benchmark_output_dir=args.benchmark_output_dir,
        gold_paper_ids=args.gold_paper_id,
        quality_gate=args.quality_gate,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if (
        args.quality_gate
        and (summary.get("quality_gate") or {}).get("status") == "fail"
    ):
        raise SystemExit(1)


def run_objective_gold_benchmark(
    *,
    backend_root: str | Path = DEFAULT_BACKEND_ROOT,
    collection_id: str | None = None,
    source_output_dir: str | Path | None = None,
    gold_input_dir: str | Path = DEFAULT_GOLD_DIR,
    benchmark_output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    gold_paper_ids: list[str] | None = None,
    quality_gate: bool = False,
) -> dict[str, Any]:
    destination = Path(benchmark_output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    gold_path = destination / "gold_bundle.json"
    prediction_path = destination / "objective_prediction_bundle.json"
    report_path = destination / "objective_evaluation_report.json"
    target_prediction_path = destination / "research_objective_target_prediction.json"
    target_report_path = destination / "research_objective_target_report.json"

    converted_gold_path = convert_expert_gold.convert_expert_gold(
        input_dir=gold_input_dir,
        output_path=gold_path,
    )
    exported_prediction_path = export_prediction_bundle.export_prediction_bundle(
        backend_root=backend_root,
        collection_id=collection_id,
        source_output_dir=source_output_dir,
        output_path=prediction_path,
        fact_source="objective_first",
    )
    evaluation_report_path = evaluate_gold_vs_prediction.evaluate_gold_vs_prediction(
        gold_path=converted_gold_path,
        prediction_path=exported_prediction_path,
        output_path=report_path,
        gold_paper_ids=gold_paper_ids,
    )
    research_objective_prediction_path = (
        build_research_objective_target_prediction.build_research_objective_target_prediction(
            prediction_bundle_path=exported_prediction_path,
            output_path=target_prediction_path,
            report_path=target_report_path,
        )
    )
    report = json.loads(evaluation_report_path.read_text(encoding="utf-8"))
    target_report = json.loads(target_report_path.read_text(encoding="utf-8"))
    summary = {
        "gold_bundle": str(converted_gold_path),
        "prediction_bundle": str(exported_prediction_path),
        "evaluation_report": str(evaluation_report_path),
        "research_objective_target_prediction": str(research_objective_prediction_path),
        "research_objective_target_report": str(target_report_path),
        "research_objective_target": _research_objective_target_summary(
            target_report
        ),
        "summary": report.get("summary", {}),
        "paper_mapping_quality": evaluate_paper_mapping_quality(
            report.get("papers", [])
        ),
        "papers": _paper_summaries(report.get("papers", [])),
    }
    if quality_gate:
        summary["quality_gate"] = evaluate_objective_quality_gate(report)
    return summary


def _research_objective_target_summary(report: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if "scores" in report:
        summary["scores"] = report["scores"]
    if "quality_gate" in report:
        summary["quality_gate"] = report["quality_gate"]
    return summary


def evaluate_objective_quality_gate(
    report: dict[str, Any],
    thresholds: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    gates = thresholds or DEFAULT_QUALITY_THRESHOLDS
    papers = {
        str(paper.get("gold_paper_id") or ""): paper
        for paper in report.get("papers", [])
        if isinstance(paper, dict)
    }
    checks: list[dict[str, Any]] = []
    for paper_id, paper_thresholds in gates.items():
        paper = papers.get(paper_id)
        if paper is None:
            checks.append(
                {
                    "status": "fail",
                    "paper_id": paper_id,
                    "metric": "paper_present",
                    "actual": None,
                    "minimum": 1,
                }
            )
            continue
        for metric, minimum in paper_thresholds.items():
            actual = _quality_metric_value(paper, metric)
            passed = actual is not None and actual >= minimum
            checks.append(
                {
                    "status": "pass" if passed else "fail",
                    "paper_id": paper_id,
                    "metric": metric,
                    "actual": actual,
                    "minimum": minimum,
                }
            )
    failed_checks = [check for check in checks if check["status"] == "fail"]
    return {
        "status": "fail" if failed_checks else "pass",
        "checks": checks,
        "failed_checks": failed_checks,
    }


def evaluate_paper_mapping_quality(papers: list[dict[str, Any]]) -> dict[str, Any]:
    mapped_prediction_ids: dict[str, list[str]] = {}
    unmapped_gold_paper_ids: list[str] = []
    for paper in papers:
        gold_paper_id = str(paper.get("gold_paper_id") or "")
        mapping_status = str((paper.get("paper_mapping") or {}).get("status") or "")
        prediction_paper_id = str(paper.get("prediction_paper_id") or "")
        if not mapping_status.startswith("mapped") or not prediction_paper_id:
            if gold_paper_id:
                unmapped_gold_paper_ids.append(gold_paper_id)
            continue
        mapped_prediction_ids.setdefault(prediction_paper_id, []).append(gold_paper_id)
    duplicate_prediction_mappings = [
        {
            "prediction_paper_id": prediction_paper_id,
            "gold_paper_ids": gold_paper_ids,
        }
        for prediction_paper_id, gold_paper_ids in sorted(mapped_prediction_ids.items())
        if len(gold_paper_ids) > 1
    ]
    status = (
        "fail"
        if duplicate_prediction_mappings or unmapped_gold_paper_ids
        else "pass"
    )
    return {
        "status": status,
        "mapped_paper_count": sum(len(ids) for ids in mapped_prediction_ids.values()),
        "unique_prediction_paper_count": len(mapped_prediction_ids),
        "duplicate_prediction_mappings": duplicate_prediction_mappings,
        "unmapped_gold_paper_ids": unmapped_gold_paper_ids,
    }


def _quality_metric_value(paper: dict[str, Any], metric: str) -> float | None:
    if metric in {"measurement_recall", "prediction_core_measurement_count"}:
        measurements = paper.get("measurements") or {}
        if metric == "measurement_recall":
            return _number_or_none(measurements.get("recall"))
        return _number_or_none(measurements.get("prediction_core_count"))
    if metric in {"comparison_recall", "comparison_precision"}:
        comparisons = paper.get("comparisons") or {}
        if metric == "comparison_recall":
            return _number_or_none(comparisons.get("recall"))
        return _number_or_none(comparisons.get("precision"))
    return None


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _paper_summaries(papers: Any) -> list[dict[str, Any]]:
    if not isinstance(papers, list):
        return []
    summaries: list[dict[str, Any]] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        summaries.append(
            {
                "gold_paper_id": paper.get("gold_paper_id"),
                "prediction_paper_id": paper.get("prediction_paper_id"),
                "mapping_status": (paper.get("paper_mapping") or {}).get("status"),
                "sample_recall": (paper.get("samples") or {}).get("recall"),
                "measurement_recall": (paper.get("measurements") or {}).get(
                    "recall"
                ),
                "test_condition_recall": (paper.get("test_conditions") or {}).get(
                    "recall"
                ),
                "comparison_recall": (paper.get("comparisons") or {}).get("recall"),
                "missing_gold_measurements": (
                    paper.get("measurements") or {}
                ).get("missing_gold_count"),
                "missing_gold_comparisons": (
                    paper.get("comparisons") or {}
                ).get("missing_gold_count"),
            }
        )
    return summaries


if __name__ == "__main__":
    main()
