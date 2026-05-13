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

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import convert_expert_gold  # noqa: E402
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
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def run_objective_gold_benchmark(
    *,
    backend_root: str | Path = DEFAULT_BACKEND_ROOT,
    collection_id: str | None = None,
    source_output_dir: str | Path | None = None,
    gold_input_dir: str | Path = DEFAULT_GOLD_DIR,
    benchmark_output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    gold_paper_ids: list[str] | None = None,
) -> dict[str, Any]:
    destination = Path(benchmark_output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    gold_path = destination / "gold_bundle.json"
    prediction_path = destination / "objective_prediction_bundle.json"
    report_path = destination / "objective_evaluation_report.json"

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
    report = json.loads(evaluation_report_path.read_text(encoding="utf-8"))
    return {
        "gold_bundle": str(converted_gold_path),
        "prediction_bundle": str(exported_prediction_path),
        "evaluation_report": str(evaluation_report_path),
        "summary": report.get("summary", {}),
        "papers": _paper_summaries(report.get("papers", [])),
    }


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
