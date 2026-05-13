#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "expert-gold-evaluation-report-v0.1"
DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BUNDLE_DIR = DEFAULT_BACKEND_ROOT / "tests" / "fixtures" / "local_expert_gold" / "generated"
DEFAULT_GOLD_PATH = DEFAULT_BUNDLE_DIR / "gold_bundle.json"
DEFAULT_PREDICTION_PATH = DEFAULT_BUNDLE_DIR / "prediction_bundle.json"
DEFAULT_OUTPUT_PATH = DEFAULT_BUNDLE_DIR / "evaluation_report.json"
DEFAULT_ABSOLUTE_TOLERANCE = 1e-6
DEFAULT_RELATIVE_TOLERANCE = 1e-3

METRIC_ALIASES = {
    "relative density": "density",
    "density": "density",
    "densification": "density",
    "porosity": "density",
    "microhardness": "hardness",
    "hardness": "hardness",
    "vickers hardness": "hardness",
    "yield strength": "yield_strength",
    "yield_strength": "yield_strength",
    "ys": "yield_strength",
    "ultimate tensile strength": "tensile_strength",
    "tensile strength": "tensile_strength",
    "tensile_strength": "tensile_strength",
    "uts": "tensile_strength",
    "elongation": "elongation",
    "elongation at break": "elongation",
    "ductility": "ductility",
    "corrosion potential": "corrosion_potential",
    "corrosion_potential": "corrosion_potential",
    "e corr": "corrosion_potential",
    "ecorr": "corrosion_potential",
    "pitting potential": "pitting_potential_ep",
    "pitting_potential": "pitting_potential_ep",
    "pitting potential ep": "pitting_potential_ep",
    "pitting_potential_ep": "pitting_potential_ep",
    "e p": "pitting_potential_ep",
    "ep": "pitting_potential_ep",
    "passivation interval": "passivation_interval_ep_ed",
    "passivation_interval": "passivation_interval_ep_ed",
    "passivation interval ep ed": "passivation_interval_ep_ed",
    "passivation_interval_ep_ed": "passivation_interval_ep_ed",
    "e p e d": "passivation_interval_ep_ed",
    "ep ed": "passivation_interval_ep_ed",
    "film resistance": "passive_film_resistance_rfilm",
    "passive film resistance": "passive_film_resistance_rfilm",
    "passive_film_resistance": "passive_film_resistance_rfilm",
    "passive film resistance rfilm": "passive_film_resistance_rfilm",
    "passive_film_resistance_rfilm": "passive_film_resistance_rfilm",
    "r film": "passive_film_resistance_rfilm",
    "rfilm": "passive_film_resistance_rfilm",
    "yield strength trend": "yield_strength_trend",
    "yield_strength_trend": "yield_strength_trend",
    "corrosion resistance": "corrosion_resistance",
    "corrosion_resistance": "corrosion_resistance",
}
CORE_METRICS = {
    "density",
    "hardness",
    "yield_strength",
    "tensile_strength",
    "elongation",
}


@dataclass(frozen=True)
class MeasurementItem:
    index: int
    record: dict[str, Any]
    sample_key: str
    metric: str
    value: float | None
    unit: str
    evidence_ids: list[str]


@dataclass(frozen=True)
class ComparisonItem:
    index: int
    record: dict[str, Any]
    current_sample_key: str
    baseline_sample_key: str
    metric: str
    current_value: float | None
    baseline_value: float | None
    unit: str
    evidence_ids: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare an expert gold bundle with a system prediction bundle."
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=DEFAULT_GOLD_PATH,
        help="Gold bundle JSON path. Defaults to local_expert_gold/generated/gold_bundle.json.",
    )
    parser.add_argument(
        "--prediction",
        type=Path,
        default=DEFAULT_PREDICTION_PATH,
        help=(
            "Prediction bundle JSON path. Defaults to "
            "local_expert_gold/generated/prediction_bundle.json."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Evaluation report JSON path. Defaults to local_expert_gold/generated/evaluation_report.json.",
    )
    parser.add_argument(
        "--gold-paper-id",
        action="append",
        help=(
            "Evaluate one gold paper id. May be repeated. Defaults to every "
            "gold paper that can be mapped to a prediction paper."
        ),
    )
    parser.add_argument(
        "--absolute-tolerance",
        type=float,
        default=DEFAULT_ABSOLUTE_TOLERANCE,
        help="Absolute numeric tolerance for value matching.",
    )
    parser.add_argument(
        "--relative-tolerance",
        type=float,
        default=DEFAULT_RELATIVE_TOLERANCE,
        help="Relative numeric tolerance for value matching.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = evaluate_gold_vs_prediction(
        gold_path=args.gold,
        prediction_path=args.prediction,
        output_path=args.output,
        gold_paper_ids=args.gold_paper_id,
        absolute_tolerance=args.absolute_tolerance,
        relative_tolerance=args.relative_tolerance,
    )
    print(output_path)


def evaluate_gold_vs_prediction(
    *,
    gold_path: str | Path = DEFAULT_GOLD_PATH,
    prediction_path: str | Path = DEFAULT_PREDICTION_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    gold_paper_ids: list[str] | None = None,
    absolute_tolerance: float = DEFAULT_ABSOLUTE_TOLERANCE,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> Path:
    gold_file = Path(gold_path).expanduser().resolve()
    prediction_file = Path(prediction_path).expanduser().resolve()
    if not gold_file.is_file():
        raise SystemExit(f"gold bundle not found: {gold_file}")
    if not prediction_file.is_file():
        raise SystemExit(f"prediction bundle not found: {prediction_file}")

    gold = _read_json(gold_file)
    prediction = _read_json(prediction_file)
    report = build_evaluation_report(
        gold=gold,
        prediction=prediction,
        gold_path=gold_file,
        prediction_path=prediction_file,
        gold_paper_ids=gold_paper_ids,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
    )
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def build_evaluation_report(
    *,
    gold: dict[str, Any],
    prediction: dict[str, Any],
    gold_path: Path,
    prediction_path: Path,
    gold_paper_ids: list[str] | None,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, Any]:
    selected_gold_papers = _select_gold_papers(gold, gold_paper_ids)
    prediction_papers = _list_records(prediction, "papers")
    paper_reports: list[dict[str, Any]] = []
    for gold_paper in selected_gold_papers:
        mapping = _map_prediction_paper(gold_paper, prediction_papers)
        prediction_paper = mapping.get("prediction_paper") or {}
        paper_reports.append(
            _evaluate_paper(
                gold=gold,
                prediction=prediction,
                gold_paper=gold_paper,
                prediction_paper=prediction_paper,
                mapping_status=str(mapping["status"]),
                mapping_reason=str(mapping["reason"]),
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            )
        )

    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "gold_bundle": str(gold_path),
            "prediction_bundle": str(prediction_path),
            "gold_schema_version": (gold.get("metadata") or {}).get("schema_version"),
            "prediction_schema_version": (prediction.get("metadata") or {}).get(
                "schema_version"
            ),
            "absolute_tolerance": absolute_tolerance,
            "relative_tolerance": relative_tolerance,
        },
        "summary": _summarize_paper_reports(paper_reports),
        "papers": paper_reports,
    }


def _evaluate_paper(
    *,
    gold: dict[str, Any],
    prediction: dict[str, Any],
    gold_paper: dict[str, Any],
    prediction_paper: dict[str, Any],
    mapping_status: str,
    mapping_reason: str,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, Any]:
    gold_paper_id = _text(gold_paper.get("paper_id"))
    prediction_paper_id = _text(prediction_paper.get("paper_id"))
    gold_records = _paper_scoped_records(gold, gold_paper_id)
    prediction_records = _paper_scoped_records(prediction, prediction_paper_id)
    sample_report = _evaluate_samples(
        gold_records["samples"],
        prediction_records["samples"],
    )
    measurement_report = _evaluate_measurements(
        gold_records["measurement_results"],
        prediction_records["measurement_results"],
        prediction_records["samples"],
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
    )
    return {
        "gold_paper_id": gold_paper_id,
        "prediction_paper_id": prediction_paper_id,
        "paper_mapping": {
            "status": mapping_status,
            "reason": mapping_reason,
            "gold_title": gold_paper.get("title"),
            "prediction_title": prediction_paper.get("title"),
            "prediction_source_filename": prediction_paper.get("source_filename"),
        },
        "paper_metadata": _evaluate_paper_metadata(gold_paper, prediction_paper),
        "samples": sample_report,
        "measurements": measurement_report,
        "test_conditions": _evaluate_test_conditions(
            gold_records["test_conditions"],
            prediction_records["test_conditions"],
        ),
        "comparisons": _evaluate_comparisons(
            gold_records["comparisons"],
            prediction_records["comparisons"],
            prediction_records["samples"],
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        ),
        "evidence": _evaluate_evidence(
            prediction_records,
            measurement_report["exact_matches"],
        ),
        "observations": {
            "gold_count": len(gold_records["observations"]),
            "prediction_count": len(prediction_records["observations"]),
        },
        "counts": {
            "gold": {
                key: len(value)
                for key, value in gold_records.items()
            },
            "prediction": {
                key: len(value)
                for key, value in prediction_records.items()
            },
        },
    }


def _evaluate_paper_metadata(
    gold_paper: dict[str, Any],
    prediction_paper: dict[str, Any],
) -> dict[str, Any]:
    gold_title = _text(gold_paper.get("title"))
    prediction_title = _text(prediction_paper.get("title"))
    gold_doi = _normalize_doi(gold_paper.get("doi"))
    prediction_doi = _normalize_doi(prediction_paper.get("doi"))
    return {
        "title_match": _title_match(gold_title, prediction_title),
        "doi_match": bool(gold_doi and prediction_doi and gold_doi == prediction_doi),
        "gold_doi": gold_doi,
        "prediction_doi": prediction_doi,
        "prediction_has_doi": bool(prediction_doi),
        "prediction_document_type": prediction_paper.get("document_type"),
    }


def _evaluate_samples(
    gold_samples: list[dict[str, Any]],
    prediction_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    gold_by_key: dict[str, dict[str, Any]] = {}
    for sample in gold_samples:
        key = _sample_key_from_gold(sample)
        if key:
            gold_by_key.setdefault(key, sample)

    prediction_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    generic_predictions: list[dict[str, Any]] = []
    for sample in prediction_samples:
        key = _sample_key_from_prediction(sample)
        if key:
            prediction_by_key[key].append(sample)
        else:
            generic_predictions.append(sample)

    matched_keys = sorted(set(gold_by_key).intersection(prediction_by_key), key=_sort_key)
    missing = [
        _sample_brief(gold_by_key[key])
        for key in sorted(set(gold_by_key) - set(prediction_by_key), key=_sort_key)
    ]
    extra_numeric = [
        _sample_brief(sample)
        for key in sorted(set(prediction_by_key) - set(gold_by_key), key=_sort_key)
        for sample in prediction_by_key[key]
    ]
    duplicate_predictions = {
        key: [_sample_brief(sample) for sample in values]
        for key, values in prediction_by_key.items()
        if key in gold_by_key and len(values) > 1
    }
    return {
        "gold_count": len(gold_samples),
        "prediction_count": len(prediction_samples),
        "matched_count": len(matched_keys),
        "recall": _ratio(len(matched_keys), len(gold_by_key)),
        "matched_sample_keys": matched_keys,
        "missing_gold_samples": missing,
        "extra_numeric_prediction_samples": extra_numeric,
        "extra_generic_prediction_samples": [
            _sample_brief(sample) for sample in generic_predictions
        ],
        "duplicate_prediction_samples": duplicate_predictions,
    }


def _evaluate_measurements(
    gold_results: list[dict[str, Any]],
    prediction_results: list[dict[str, Any]],
    prediction_samples: list[dict[str, Any]],
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, Any]:
    prediction_sample_keys = {
        _text(sample.get("sample_id")): _sample_key_from_prediction(sample)
        for sample in prediction_samples
    }
    gold_items = [
        item
        for item in (
            _gold_measurement_item(index, row)
            for index, row in enumerate(gold_results)
        )
        if item.metric in CORE_METRICS and item.sample_key
    ]
    prediction_items = [
        item
        for item in (
            _prediction_measurement_item(index, row, prediction_sample_keys)
            for index, row in enumerate(prediction_results)
        )
        if item.metric in CORE_METRICS and item.sample_key
    ]
    prediction_by_key: dict[tuple[str, str], list[MeasurementItem]] = defaultdict(list)
    for item in prediction_items:
        prediction_by_key[(item.sample_key, item.metric)].append(item)

    used_prediction_indexes: set[int] = set()
    exact_matches: list[dict[str, Any]] = []
    value_mismatches: list[dict[str, Any]] = []
    missing_gold_results: list[dict[str, Any]] = []

    for gold_item in gold_items:
        candidates = prediction_by_key.get((gold_item.sample_key, gold_item.metric), [])
        exact_candidate = _first_exact_candidate(
            gold_item,
            candidates,
            used_prediction_indexes=used_prediction_indexes,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        )
        if exact_candidate is not None:
            used_prediction_indexes.add(exact_candidate.index)
            exact_matches.append(
                {
                    "gold": _measurement_brief(gold_item),
                    "prediction": _measurement_brief(exact_candidate),
                }
            )
            continue
        if candidates:
            value_mismatches.append(
                {
                    "gold": _measurement_brief(gold_item),
                    "prediction_candidates": [
                        _measurement_brief(candidate)
                        for candidate in candidates[:5]
                    ],
                }
            )
            continue
        missing_gold_results.append(_measurement_brief(gold_item))

    extra_predictions = [
        _measurement_brief(item)
        for item in prediction_items
        if item.index not in used_prediction_indexes
    ]
    duplicate_predictions = _duplicate_measurements(prediction_items)
    metric_counts = {
        "gold_core": Counter(item.metric for item in gold_items),
        "prediction_core": Counter(item.metric for item in prediction_items),
        "prediction_all": Counter(
            _normalize_metric(row.get("metric_name"))
            for row in prediction_results
            if _normalize_metric(row.get("metric_name"))
        ),
    }
    return {
        "gold_core_count": len(gold_items),
        "prediction_core_count": len(prediction_items),
        "exact_match_count": len(exact_matches),
        "value_mismatch_count": len(value_mismatches),
        "missing_gold_count": len(missing_gold_results),
        "extra_prediction_count": len(extra_predictions),
        "recall": _ratio(len(exact_matches), len(gold_items)),
        "precision": _ratio(len(exact_matches), len(prediction_items)),
        "metric_counts": {
            key: dict(counter)
            for key, counter in metric_counts.items()
        },
        "exact_matches": exact_matches,
        "value_mismatches": value_mismatches,
        "missing_gold_results": missing_gold_results,
        "extra_prediction_results": extra_predictions[:100],
        "extra_prediction_results_truncated": len(extra_predictions) > 100,
        "duplicate_prediction_groups": duplicate_predictions,
    }


def _evaluate_test_conditions(
    gold_conditions: list[dict[str, Any]],
    prediction_conditions: list[dict[str, Any]],
) -> dict[str, Any]:
    gold_families = {
        _gold_condition_family(row): row
        for row in gold_conditions
    }
    gold_families.pop("", None)
    prediction_family_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in prediction_conditions:
        family = _prediction_condition_family(row)
        if family:
            prediction_family_rows[family].append(row)

    matched = sorted(set(gold_families).intersection(prediction_family_rows))
    missing = [
        {
            "condition_id": row.get("test_condition_id"),
            "test_type": row.get("test_type"),
            "family": family,
        }
        for family, row in sorted(gold_families.items())
        if family not in prediction_family_rows
    ]
    completeness_counts = Counter(
        _text(row.get("condition_completeness")) or "unspecified"
        for row in prediction_conditions
    )
    return {
        "gold_count": len(gold_conditions),
        "prediction_count": len(prediction_conditions),
        "matched_family_count": len(matched),
        "matched_families": matched,
        "missing_gold_condition_families": missing,
        "prediction_extra_families": sorted(set(prediction_family_rows) - set(gold_families)),
        "prediction_condition_completeness": dict(completeness_counts),
        "prediction_unresolved_count": completeness_counts.get("unresolved", 0),
    }


def _gold_condition_family(row: dict[str, Any]) -> str:
    return _first_condition_family(
        row.get("test_type"),
        row.get("test_standard"),
        row.get("other_conditions"),
    )


def _prediction_condition_family(row: dict[str, Any]) -> str:
    payload = row.get("condition_payload")
    payload_fields: list[Any] = []
    if isinstance(payload, dict):
        payload_fields.extend(
            [
                payload.get("method_family"),
                payload.get("test_method"),
                payload.get("method"),
                payload.get("methods"),
            ]
        )
    return _first_condition_family(
        row.get("test_type"),
        *payload_fields,
        row.get("other_conditions"),
        payload,
    )


def _first_condition_family(*values: Any) -> str:
    for value in values:
        family = _condition_family(value)
        if family:
            return family
    return ""


def _evaluate_comparisons(
    gold_comparisons: list[dict[str, Any]],
    prediction_comparisons: list[dict[str, Any]],
    prediction_samples: list[dict[str, Any]],
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, Any]:
    prediction_sample_keys = {
        _text(sample.get("sample_id")): _sample_key_from_prediction(sample)
        for sample in prediction_samples
    }
    gold_items = [
        item
        for item in (
            _gold_comparison_item(index, row)
            for index, row in enumerate(gold_comparisons)
        )
        if item.metric and item.current_sample_key and item.baseline_sample_key
    ]
    prediction_items = [
        item
        for item in (
            _prediction_comparison_item(index, row, prediction_sample_keys)
            for index, row in enumerate(prediction_comparisons)
        )
        if item.metric and item.current_sample_key and item.baseline_sample_key
    ]

    prediction_by_key: dict[tuple[str, str, str], list[ComparisonItem]] = defaultdict(
        list
    )
    for item in prediction_items:
        prediction_by_key[
            (item.current_sample_key, item.baseline_sample_key, item.metric)
        ].append(item)

    used_prediction_indexes: set[int] = set()
    exact_matches: list[dict[str, Any]] = []
    value_mismatches: list[dict[str, Any]] = []
    missing_gold_comparisons: list[dict[str, Any]] = []

    for gold_item in gold_items:
        candidates = prediction_by_key.get(
            (
                gold_item.current_sample_key,
                gold_item.baseline_sample_key,
                gold_item.metric,
            ),
            [],
        )
        exact_candidate = _first_exact_comparison_candidate(
            gold_item,
            candidates,
            used_prediction_indexes=used_prediction_indexes,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        )
        if exact_candidate is not None:
            used_prediction_indexes.add(exact_candidate.index)
            exact_matches.append(
                {
                    "gold": _comparison_brief(gold_item),
                    "prediction": _comparison_brief(exact_candidate),
                }
            )
            continue
        if candidates:
            value_mismatches.append(
                {
                    "gold": _comparison_brief(gold_item),
                    "prediction_candidates": [
                        _comparison_brief(candidate)
                        for candidate in candidates[:5]
                    ],
                }
            )
            continue
        missing_gold_comparisons.append(_comparison_brief(gold_item))

    extra_predictions = [
        _comparison_brief(item)
        for item in prediction_items
        if item.index not in used_prediction_indexes
    ]
    return {
        "gold_count": len(gold_comparisons),
        "prediction_count": len(prediction_comparisons),
        "gold_pairwise_count": len(gold_items),
        "prediction_pairwise_count": len(prediction_items),
        "exact_match_count": len(exact_matches),
        "value_mismatch_count": len(value_mismatches),
        "missing_gold_count": len(missing_gold_comparisons),
        "extra_prediction_count": len(extra_predictions),
        "recall": _ratio(len(exact_matches), len(gold_items)),
        "precision": _ratio(len(exact_matches), len(prediction_items)),
        "pairwise_exact_matching_status": "active",
        "exact_matches": exact_matches,
        "value_mismatches": value_mismatches,
        "missing_gold_comparisons": missing_gold_comparisons,
        "extra_prediction_comparisons": extra_predictions[:100],
        "extra_prediction_comparisons_truncated": len(extra_predictions) > 100,
    }


def _evaluate_evidence(
    prediction_records: dict[str, list[dict[str, Any]]],
    exact_measurement_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    prediction_results = prediction_records["measurement_results"]
    prediction_samples = prediction_records["samples"]
    prediction_comparisons = prediction_records["comparisons"]
    matched_without_evidence = [
        match
        for match in exact_measurement_matches
        if not match["prediction"].get("evidence_ids")
    ]
    return {
        "prediction_evidence_count": len(prediction_records["evidence"]),
        "prediction_measurements_without_evidence": sum(
            1 for row in prediction_results if not row.get("evidence_ids")
        ),
        "prediction_samples_without_evidence": sum(
            1 for row in prediction_samples if not row.get("evidence_ids")
        ),
        "prediction_comparisons_without_evidence": sum(
            1
            for row in prediction_comparisons
            if not row.get("evidence_ids") and not row.get("anchor_ids")
        ),
        "matched_measurements_without_evidence": len(matched_without_evidence),
    }


def _select_gold_papers(
    gold: dict[str, Any],
    gold_paper_ids: list[str] | None,
) -> list[dict[str, Any]]:
    papers = _list_records(gold, "papers")
    if not gold_paper_ids:
        return papers
    selected = {
        _text(item)
        for item in gold_paper_ids
        if _text(item)
    }
    return [
        paper
        for paper in papers
        if _text(paper.get("paper_id")) in selected
    ]


def _map_prediction_paper(
    gold_paper: dict[str, Any],
    prediction_papers: list[dict[str, Any]],
) -> dict[str, Any]:
    gold_id = _text(gold_paper.get("paper_id"))
    gold_title = _text(gold_paper.get("title"))
    for paper in prediction_papers:
        if _text(paper.get("paper_id")) == gold_id:
            return {
                "status": "mapped",
                "reason": "paper_id exact match",
                "prediction_paper": paper,
            }

    for paper in prediction_papers:
        searchable = " ".join(
            [
                _text(paper.get("title")),
                _text(paper.get("source_filename")),
            ]
        )
        if gold_id and gold_id.lower() in searchable.lower():
            return {
                "status": "mapped",
                "reason": "gold paper id found in prediction filename/title",
                "prediction_paper": paper,
            }

    for paper in prediction_papers:
        if _title_match(gold_title, _text(paper.get("title"))):
            return {
                "status": "mapped",
                "reason": "title token match",
                "prediction_paper": paper,
            }
    if len(prediction_papers) == 1:
        return {
            "status": "mapped_with_low_confidence",
            "reason": "single prediction paper fallback",
            "prediction_paper": prediction_papers[0],
        }
    return {
        "status": "unmapped",
        "reason": "no matching prediction paper found",
        "prediction_paper": {},
    }


def _paper_scoped_records(
    bundle: dict[str, Any],
    paper_id: str,
) -> dict[str, list[dict[str, Any]]]:
    scoped: dict[str, list[dict[str, Any]]] = {}
    for key in (
        "samples",
        "process_parameters",
        "test_conditions",
        "measurement_results",
        "comparisons",
        "observations",
        "evidence",
    ):
        scoped[key] = [
            row
            for row in _list_records(bundle, key)
            if _record_paper_id(row) == paper_id
        ]
    return scoped


def _record_paper_id(row: dict[str, Any]) -> str:
    return _text(row.get("paper_id") or row.get("source_document_id") or row.get("document_id"))


def _gold_measurement_item(index: int, row: dict[str, Any]) -> MeasurementItem:
    return MeasurementItem(
        index=index,
        record=row,
        sample_key=_sample_key(row.get("sample_id")),
        metric=_normalize_metric(row.get("metric_name")),
        value=_numeric_value(row.get("value_or_trend")),
        unit=_normalize_unit(row.get("unit")),
        evidence_ids=_string_list(row.get("evidence_ids")),
    )


def _prediction_measurement_item(
    index: int,
    row: dict[str, Any],
    prediction_sample_keys: dict[str, str],
) -> MeasurementItem:
    sample_id = _text(row.get("sample_id"))
    return MeasurementItem(
        index=index,
        record=row,
        sample_key=prediction_sample_keys.get(sample_id, _sample_key(sample_id)),
        metric=_normalize_metric(row.get("metric_name")),
        value=_numeric_value(row.get("value_payload") or row.get("value_or_trend")),
        unit=_normalize_unit(row.get("unit")),
        evidence_ids=_string_list(row.get("evidence_ids")),
    )


def _gold_comparison_item(index: int, row: dict[str, Any]) -> ComparisonItem:
    baseline_sample_keys = [
        _sample_key(item)
        for item in _string_list(row.get("baseline_sample_ids"))
        if _sample_key(item)
    ]
    return ComparisonItem(
        index=index,
        record=row,
        current_sample_key=_sample_key(row.get("current_sample_id")),
        baseline_sample_key=(
            baseline_sample_keys[0]
            if baseline_sample_keys
            else _sample_key(row.get("baseline_reference"))
        ),
        metric=_normalize_metric(row.get("metric_name") or row.get("comparison_metric")),
        current_value=_numeric_value(row.get("current_value")),
        baseline_value=_numeric_value(row.get("baseline_value")),
        unit=_normalize_unit(row.get("unit")),
        evidence_ids=_string_list(row.get("evidence_ids")),
    )


def _prediction_comparison_item(
    index: int,
    row: dict[str, Any],
    prediction_sample_keys: dict[str, str],
) -> ComparisonItem:
    current_sample_id = _text(row.get("current_sample_id"))
    baseline_sample_ids = _string_list(row.get("baseline_sample_ids"))
    baseline_sample_id = baseline_sample_ids[0] if baseline_sample_ids else ""
    return ComparisonItem(
        index=index,
        record=row,
        current_sample_key=prediction_sample_keys.get(
            current_sample_id,
            _sample_key(current_sample_id),
        ),
        baseline_sample_key=prediction_sample_keys.get(
            baseline_sample_id,
            _sample_key(baseline_sample_id)
            or _sample_key(row.get("baseline_reference")),
        ),
        metric=_normalize_metric(row.get("metric_name") or row.get("comparison_metric")),
        current_value=_numeric_value(row.get("current_value")),
        baseline_value=_numeric_value(row.get("baseline_value")),
        unit=_normalize_unit(row.get("unit")),
        evidence_ids=_string_list(row.get("evidence_ids") or row.get("anchor_ids")),
    )


def _first_exact_candidate(
    gold_item: MeasurementItem,
    candidates: list[MeasurementItem],
    *,
    used_prediction_indexes: set[int],
    absolute_tolerance: float,
    relative_tolerance: float,
) -> MeasurementItem | None:
    for candidate in candidates:
        if candidate.index in used_prediction_indexes:
            continue
        if _units_compatible(gold_item.unit, candidate.unit) and _values_match(
            gold_item.value,
            candidate.value,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        ):
            return candidate
    return None


def _first_exact_comparison_candidate(
    gold_item: ComparisonItem,
    candidates: list[ComparisonItem],
    *,
    used_prediction_indexes: set[int],
    absolute_tolerance: float,
    relative_tolerance: float,
) -> ComparisonItem | None:
    for candidate in candidates:
        if candidate.index in used_prediction_indexes:
            continue
        if not _units_compatible(gold_item.unit, candidate.unit):
            continue
        if not _values_match(
            gold_item.current_value,
            candidate.current_value,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        ):
            continue
        if not _values_match(
            gold_item.baseline_value,
            candidate.baseline_value,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        ):
            continue
        return candidate
    return None


def _duplicate_measurements(items: list[MeasurementItem]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[MeasurementItem]] = defaultdict(list)
    for item in items:
        value_key = "" if item.value is None else f"{item.value:.8g}"
        groups[(item.sample_key, item.metric, value_key, item.unit)].append(item)
    return [
        {
            "sample_key": sample_key,
            "metric": metric,
            "value": value,
            "unit": unit,
            "count": len(group),
            "records": [_measurement_brief(item) for item in group[:5]],
        }
        for (sample_key, metric, value, unit), group in sorted(groups.items())
        if len(group) > 1
    ]


def _measurement_brief(item: MeasurementItem) -> dict[str, Any]:
    return {
        "id": item.record.get("result_id"),
        "sample_id": item.record.get("sample_id"),
        "sample_key": item.sample_key,
        "metric": item.metric,
        "value": item.value,
        "unit": item.unit,
        "evidence_ids": item.evidence_ids,
        "source": item.record.get("source"),
    }


def _comparison_brief(item: ComparisonItem) -> dict[str, Any]:
    return {
        "id": item.record.get("comparison_id"),
        "current_sample_id": item.record.get("current_sample_id"),
        "current_sample_key": item.current_sample_key,
        "baseline_reference": item.record.get("baseline_reference"),
        "baseline_sample_key": item.baseline_sample_key,
        "metric": item.metric,
        "current_value": item.current_value,
        "baseline_value": item.baseline_value,
        "unit": item.unit,
        "evidence_ids": item.evidence_ids,
        "source": item.record.get("source"),
    }


def _sample_brief(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": sample.get("sample_id"),
        "label": sample.get("label_in_paper") or sample.get("sample_description"),
        "sample_description": sample.get("sample_description"),
        "evidence_ids": sample.get("evidence_ids") or [],
        "source": sample.get("source"),
    }


def _summarize_paper_reports(paper_reports: list[dict[str, Any]]) -> dict[str, Any]:
    if not paper_reports:
        return {
            "papers_evaluated": 0,
            "sample_recall": None,
            "measurement_recall": None,
            "measurement_precision": None,
        }
    gold_samples = sum(report["samples"]["gold_count"] for report in paper_reports)
    matched_samples = sum(report["samples"]["matched_count"] for report in paper_reports)
    gold_measurements = sum(
        report["measurements"]["gold_core_count"]
        for report in paper_reports
    )
    prediction_measurements = sum(
        report["measurements"]["prediction_core_count"]
        for report in paper_reports
    )
    matched_measurements = sum(
        report["measurements"]["exact_match_count"]
        for report in paper_reports
    )
    gold_comparisons = sum(
        report["comparisons"]["gold_pairwise_count"]
        for report in paper_reports
    )
    prediction_comparisons = sum(
        report["comparisons"]["prediction_pairwise_count"]
        for report in paper_reports
    )
    matched_comparisons = sum(
        report["comparisons"]["exact_match_count"]
        for report in paper_reports
    )
    return {
        "papers_evaluated": len(paper_reports),
        "mapped_papers": sum(
            1
            for report in paper_reports
            if str(report["paper_mapping"]["status"]).startswith("mapped")
        ),
        "sample_recall": _ratio(matched_samples, gold_samples),
        "measurement_recall": _ratio(matched_measurements, gold_measurements),
        "measurement_precision": _ratio(matched_measurements, prediction_measurements),
        "comparison_recall": _ratio(matched_comparisons, gold_comparisons),
        "comparison_precision": _ratio(
            matched_comparisons,
            prediction_comparisons,
        ),
        "gold_sample_count": gold_samples,
        "matched_sample_count": matched_samples,
        "gold_core_measurement_count": gold_measurements,
        "prediction_core_measurement_count": prediction_measurements,
        "matched_core_measurement_count": matched_measurements,
        "gold_pairwise_comparison_count": gold_comparisons,
        "prediction_pairwise_comparison_count": prediction_comparisons,
        "matched_pairwise_comparison_count": matched_comparisons,
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _list_records(bundle: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = bundle.get(key)
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, dict)
    ]


def _sample_key_from_gold(sample: dict[str, Any]) -> str:
    return (
        _sample_key(sample.get("sample_id"))
        or _sample_key(sample.get("label_in_paper"))
        or _sample_key(sample.get("sample_description"))
    )


def _sample_key_from_prediction(sample: dict[str, Any]) -> str:
    return (
        _sample_key(sample.get("label_in_paper"))
        or _sample_key(sample.get("sample_description"))
        or _sample_key(sample.get("sample_id"))
    )


def _sample_key(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    match = re.search(r"\bS0*(\d+)\b", text, flags=re.IGNORECASE)
    if match:
        return str(int(match.group(1)))
    match = re.search(r"\bsample\s*0*(\d+)\b", text, flags=re.IGNORECASE)
    if match:
        return str(int(match.group(1)))
    if re.fullmatch(r"0*\d+", text):
        return str(int(text))
    return ""


def _normalize_metric(value: Any) -> str:
    text = _normalize_text(value).replace("-", " ").replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if text in METRIC_ALIASES:
        return METRIC_ALIASES[text]
    compact = text.replace(" ", "_")
    return METRIC_ALIASES.get(compact, compact)


def _condition_family(value: Any) -> str:
    text = _normalize_text(value)
    if any(token in text for token in ("tensile", "yield", "elongation", "mechanical")):
        return "tensile"
    if any(token in text for token in ("hardness", "microhardness", "vickers")):
        return "hardness"
    if any(token in text for token in ("density", "porosity", "microstructure", "sem", "grain")):
        return "density_characterization"
    if "\u62c9\u4f38" in text:
        return "tensile"
    if "\u786c\u5ea6" in text:
        return "hardness"
    if any(token in text for token in ("\u5bc6\u5ea6", "\u5b54\u9699", "\u7ec4\u7ec7", "\u8868\u5f81")):
        return "density_characterization"
    return ""


def _normalize_unit(value: Any) -> str:
    text = _normalize_text(value)
    text = text.replace("％", "%")
    text = text.replace("mpa", "MPa")
    text = text.replace("hv", "HV")
    return text


def _normalize_doi(value: Any) -> str:
    text = _text(value).lower()
    text = text.removeprefix("https://doi.org/")
    text = text.removeprefix("http://doi.org/")
    return text.strip()


def _normalize_text(value: Any) -> str:
    text = _text(value).lower()
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [
            _text(item)
            for item in value
            if _text(item)
        ]
    text = _text(value)
    return [text] if text else []


def _numeric_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("value", "numeric_value", "source_value_text", "value_or_trend"):
            numeric = _numeric_value(value.get(key))
            if numeric is not None:
                return numeric
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _text(value)
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _values_match(
    gold_value: float | None,
    prediction_value: float | None,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> bool:
    if gold_value is None or prediction_value is None:
        return False
    tolerance = max(absolute_tolerance, abs(gold_value) * relative_tolerance)
    return abs(gold_value - prediction_value) <= tolerance


def _units_compatible(gold_unit: str, prediction_unit: str) -> bool:
    if not gold_unit or not prediction_unit:
        return True
    return gold_unit == prediction_unit


def _title_match(gold_title: str, prediction_title: str) -> bool:
    gold_tokens = _title_tokens(gold_title)
    prediction_tokens = _title_tokens(prediction_title)
    if not gold_tokens or not prediction_tokens:
        return False
    overlap = gold_tokens.intersection(prediction_tokens)
    return _ratio(len(overlap), len(gold_tokens)) >= 0.6


def _title_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _sort_key(value: str) -> tuple[int, str]:
    if re.fullmatch(r"\d+", value):
        return (0, f"{int(value):08d}")
    return (1, value)


if __name__ == "__main__":
    main()
