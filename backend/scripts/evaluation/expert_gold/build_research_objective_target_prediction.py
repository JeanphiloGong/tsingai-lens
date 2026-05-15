#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TARGET_PATH = (
    DEFAULT_BACKEND_ROOT
    / "tests"
    / "fixtures"
    / "research_objective_targets"
    / "lpbf_slm_316l_collection_target.json"
)
DEFAULT_OUTPUT_PATH = (
    DEFAULT_BACKEND_ROOT
    / "tests"
    / "fixtures"
    / "research_objective_targets"
    / "generated_prediction_from_bundle.json"
)

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import evaluate_research_objective_target  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Project an expert-gold prediction bundle into the "
            "research-objective target-prediction shape."
        )
    )
    parser.add_argument(
        "--prediction-bundle",
        type=Path,
        required=True,
        help="Prediction bundle from export_prediction_bundle.py.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Destination target-prediction JSON.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET_PATH,
        help="Optional target JSON used when --report is provided.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional destination target evaluation report.",
    )
    parser.add_argument(
        "--quality-gate",
        action="store_true",
        help="Exit non-zero when --report is provided and the gate fails.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prediction_path = build_research_objective_target_prediction(
        prediction_bundle_path=args.prediction_bundle,
        output_path=args.output,
        target_path=args.target,
        report_path=args.report,
    )
    result: dict[str, Any] = {"prediction": str(prediction_path)}
    if args.report:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        result["report"] = str(args.report)
        result["quality_gate"] = report.get("quality_gate")
        if args.quality_gate and (report.get("quality_gate") or {}).get(
            "status"
        ) == "fail":
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_research_objective_target_prediction(
    *,
    prediction_bundle_path: str | Path,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    target_path: str | Path = DEFAULT_TARGET_PATH,
    report_path: str | Path | None = None,
) -> Path:
    bundle = _read_json(Path(prediction_bundle_path))
    target = _read_json(Path(target_path))
    prediction = build_target_prediction_from_bundle(bundle, target=target)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(prediction, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if report_path is not None:
        evaluate_research_objective_target.evaluate_research_objective_target(
            target_path=target_path,
            prediction_path=destination,
            output_path=report_path,
        )
    return destination


def build_target_prediction_from_bundle(
    bundle: dict[str, Any],
    *,
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    papers = _records(bundle.get("papers"))
    samples = _records(bundle.get("samples"))
    test_conditions = _records(bundle.get("test_conditions"))
    measurements = _records(bundle.get("measurement_results"))
    comparisons = _records(bundle.get("comparisons"))
    observations = _records(bundle.get("observations"))
    uncertainties = _records(bundle.get("uncertainties"))
    evidence = _records(bundle.get("evidence"))
    paper_id_aliases = _paper_id_aliases_from_target(
        papers=papers,
        measurements=measurements,
        target=target or {},
    )
    return {
        "objective": _collection_objective_from_papers(papers),
        "evidence_scope": {
            "paper_count": len(papers),
            "sample_count": len(samples),
            "test_condition_count": len(test_conditions),
            "measurement_count": len(measurements),
            "comparison_count": len(comparisons),
            "observation_count": len(observations),
            "uncertainty_count": len(uncertainties),
        },
        "paper_contributions": _paper_contributions(
            papers=papers,
            samples=samples,
            measurements=measurements,
            paper_id_aliases=paper_id_aliases,
        ),
        "measurement_results": _measurement_summaries(
            measurements,
            paper_id_aliases=paper_id_aliases,
        ),
        "controlled_comparisons": [
            _comparison_summary(comparison)
            for comparison in comparisons
        ],
        "mechanism_chains": [
            _observation_mechanism_summary(observation)
            for observation in observations
        ],
        "collection_conclusion": {
            "summary": (
                "Projected from prediction bundle records. Expert narration "
                "is evaluated through required claim coverage."
            )
        },
        "limitations": [
            _uncertainty_summary(uncertainty)
            for uncertainty in uncertainties
        ],
        "source_traceback": [
            _evidence_summary(evidence_record)
            for evidence_record in evidence
        ],
    }


def _collection_objective_from_papers(papers: list[dict[str, Any]]) -> dict[str, Any]:
    material_scope = _unique_values(papers, "material_system")
    process_scope = _unique_values(papers, "process_type")
    property_scope = _unique_split_values(papers, "target_properties")
    return {
        "question": (
            "What does the prediction bundle support about the collection "
            "research objective?"
        ),
        "material_scope": material_scope,
        "process_scope": process_scope,
        "property_scope": property_scope,
    }


def _paper_contributions(
    *,
    papers: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    paper_id_aliases: dict[str, str],
) -> list[dict[str, Any]]:
    contributions: list[dict[str, Any]] = []
    for paper in papers:
        source_paper_id = _text(paper.get("paper_id"))
        paper_id = paper_id_aliases.get(source_paper_id, source_paper_id)
        paper_samples = [
            row for row in samples if _text(row.get("paper_id")) == source_paper_id
        ]
        paper_measurements = [
            row for row in measurements if _text(row.get("paper_id")) == source_paper_id
        ]
        metrics = _unique_values(paper_measurements, "metric_name")
        contribution = {
            "paper_id": paper_id,
            "role": "prediction_bundle_paper",
            "summary": (
                f"{paper_id}: {_text(paper.get('title'))}. "
                f"Goal: {_text(paper.get('research_goal'))}. "
                f"Variables: {_text(paper.get('main_variables'))}. "
                f"Properties: {_text(paper.get('target_properties'))}. "
                f"Samples: {len(paper_samples)}. "
                f"Measurements: {', '.join(metrics)}."
            ),
        }
        if paper_id != source_paper_id:
            contribution["source_paper_id"] = source_paper_id
        contributions.append(contribution)
    return contributions


def _paper_id_aliases_from_target(
    *,
    papers: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    target: dict[str, Any],
) -> dict[str, str]:
    target_items = _records(target.get("required_paper_contributions"))
    if not target_items:
        return {}
    aliases: dict[str, str] = {}
    used_target_ids: set[str] = set()
    for paper in papers:
        source_paper_id = _text(paper.get("paper_id"))
        paper_measurements = [
            row for row in measurements if _text(row.get("paper_id")) == source_paper_id
        ]
        search_text = _paper_match_text(paper, paper_measurements)
        best_target_id = ""
        best_score = 0
        best_required_count = 0
        for target_item in target_items:
            target_paper_id = _text(target_item.get("paper_id"))
            if not target_paper_id or target_paper_id in used_target_ids:
                continue
            required_terms = _string_list(target_item.get("required_terms"))
            score = sum(
                1 for term in required_terms if _text_contains(search_text, term)
            )
            if score > best_score:
                best_target_id = target_paper_id
                best_score = score
                best_required_count = len(required_terms)
        minimum_score = min(2, best_required_count) if best_required_count else 1
        if best_target_id and best_score >= minimum_score:
            aliases[source_paper_id] = best_target_id
            used_target_ids.add(best_target_id)
    return aliases


def _paper_match_text(
    paper: dict[str, Any],
    measurements: list[dict[str, Any]],
) -> str:
    metrics = _unique_values(measurements, "metric_name")
    values = [
        _text(paper.get("paper_id")),
        _text(paper.get("title")),
        _text(paper.get("source_filename")),
        _text(paper.get("research_goal")),
        _text(paper.get("main_variables")),
        _text(paper.get("target_properties")),
        " ".join(metrics),
    ]
    return _normalize_text(" ".join(value for value in values if value))


def _measurement_summaries(
    measurements: list[dict[str, Any]],
    *,
    paper_id_aliases: dict[str, str],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for measurement in measurements:
        source_paper_id = _text(measurement.get("paper_id"))
        paper_id = paper_id_aliases.get(source_paper_id, source_paper_id)
        result_id = _text(measurement.get("result_id"))
        sample_id = _measurement_sample_id(measurement)
        metric = _text(measurement.get("metric_name"))
        value = _measurement_value_with_unit(
            measurement.get("value_or_trend"),
            _text(measurement.get("unit")),
        )
        aliases = _measurement_value_aliases(
            value=value,
            unit=_text(measurement.get("unit")),
            metric=metric,
        )
        summary = f"{paper_id} {result_id}: {sample_id} {metric} = {value}."
        record = {
            "paper_id": paper_id,
            "result_id": result_id,
            "sample_id": sample_id,
            "metric_name": metric,
            "value": value,
            "summary": summary,
        }
        if aliases:
            record["summary"] = f"{summary} Aliases: {', '.join(aliases)}."
            record["value_aliases"] = aliases
        summaries.append(record)
    return summaries


def _measurement_sample_id(measurement: dict[str, Any]) -> str:
    sample_id = _text(measurement.get("sample_id"))
    if sample_id:
        return sample_id
    sample_ids = measurement.get("sample_ids")
    if not isinstance(sample_ids, list):
        return ""
    return ", ".join(_text(item) for item in sample_ids if _text(item))


def _measurement_value_with_unit(value: Any, unit: str) -> str:
    text = _text(value)
    if not unit or unit in text:
        return text
    if unit == "%":
        return f"{text}%"
    return f"{text} {unit}".strip()


def _measurement_value_aliases(*, value: str, unit: str, metric: str) -> list[str]:
    aliases: list[str] = []
    if _measurement_is_percent_like(unit=unit, metric=metric):
        number = _first_number(value)
        if number and f"{number}%" != value:
            aliases.append(f"{number}%")
    scientific_alias = _scientific_notation_alias(value)
    if scientific_alias:
        aliases.append(scientific_alias)
    return _dedupe_strings(aliases)


def _measurement_is_percent_like(*, unit: str, metric: str) -> bool:
    return "%" in unit or "%" in metric


def _scientific_notation_alias(value: str) -> str:
    match = re.search(
        r"(?P<base>\d+(?:\.\d+)?)\s*[x×]\s*10\s*\^?\s*(?P<exponent>[+-]?\d+)",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    unit_text = _scientific_notation_unit_text(value[match.end() :])
    alias = f"{match.group('base')}e{match.group('exponent')}"
    return f"{alias} {unit_text}".strip()


def _scientific_notation_unit_text(value: str) -> str:
    text = value.replace("Ω", "ohm").replace("ω", "ohm")
    text = " ".join(text.split())
    text = re.sub(r"\bcm\s+2\b", "cm2", text, flags=re.IGNORECASE)
    return text


def _first_number(value: str) -> str:
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value)
    return match.group(0) if match else ""


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _comparison_summary(comparison: dict[str, Any]) -> dict[str, Any]:
    paper_id = _text(comparison.get("paper_id"))
    comparison_id = _text(comparison.get("comparison_id"))
    current_sample = _text(comparison.get("current_sample_id"))
    baseline = _text(comparison.get("baseline_reference"))
    metric = _text(comparison.get("metric_name"))
    unit = _text(comparison.get("unit"))
    current_value = _value_with_unit(comparison.get("current_value"), unit)
    baseline_value = _value_with_unit(comparison.get("baseline_value"), unit)
    direction = _text(comparison.get("direction"))
    notes = _text(comparison.get("notes"))
    return {
        "paper_id": paper_id,
        "comparison_id": comparison_id,
        "summary": (
            f"{paper_id} {comparison_id}: {current_sample} vs {baseline} "
            f"for {metric}. {current_value} vs {baseline_value}. "
            f"Direction: {direction}. Notes: {_without_trailing_period(notes)}."
        ),
    }


def _observation_mechanism_summary(observation: dict[str, Any]) -> dict[str, Any]:
    paper_id = _text(observation.get("paper_id"))
    observation_id = _text(observation.get("observation_id"))
    method = _text(observation.get("characterization_method"))
    observed_object = _text(observation.get("observed_object"))
    description = _text(observation.get("value_or_description"))
    interpretation = _text(observation.get("author_interpretation"))
    return {
        "paper_id": paper_id,
        "observation_id": observation_id,
        "path": (
            f"{method} observes {observed_object}: "
            f"{_without_trailing_period(description)}. "
            f"Interpretation: {_without_trailing_period(interpretation)}."
        ),
    }


def _uncertainty_summary(uncertainty: dict[str, Any]) -> str:
    paper_id = _text(uncertainty.get("paper_id"))
    issue_id = _text(uncertainty.get("issue_id"))
    description = _text(uncertainty.get("description"))
    impact = _text(uncertainty.get("impact"))
    return (
        f"{paper_id} {issue_id}: {_without_trailing_period(description)}. "
        f"Impact: {_without_trailing_period(impact)}."
    )


def _evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": _text(evidence.get("paper_id")),
        "evidence_id": _text(evidence.get("evidence_id")),
        "source": _text(evidence.get("figure_or_table")),
        "section": _text(evidence.get("section")),
        "supports": _text(evidence.get("supports")),
    }


def _value_with_unit(value: Any, unit: str) -> str:
    text = _text(value)
    if unit and unit not in text:
        return f"{text} {unit}".strip()
    return text


def _without_trailing_period(value: str) -> str:
    return value.rstrip().rstrip(".")


def _unique_values(records: list[dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for record in records:
        value = _text(record.get(key))
        if not value or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        values.append(value)
    return values


def _unique_split_values(records: list[dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for record in records:
        for raw_value in _text(record.get(key)).replace("；", ";").split(";"):
            value = raw_value.strip()
            if not value or value.casefold() in seen:
                continue
            seen.add(value.casefold())
            values.append(value)
    return values


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _text_contains(text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    return bool(normalized_term and normalized_term in text)


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().replace("；", ";").split())


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


if __name__ == "__main__":
    main()
