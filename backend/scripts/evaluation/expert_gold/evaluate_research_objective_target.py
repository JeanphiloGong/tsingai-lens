#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TARGET_PATH = (
    DEFAULT_BACKEND_ROOT
    / "tests"
    / "fixtures"
    / "research_objective_targets"
    / "lpbf_slm_316l_collection_target.json"
)
DEFAULT_REPORT_PATH = (
    DEFAULT_BACKEND_ROOT
    / "tests"
    / "fixtures"
    / "research_objective_targets"
    / "generated_target_report.json"
)
DEFAULT_QUALITY_THRESHOLDS = {
    "evidence_scope_score": 0.8,
    "paper_contribution_score": 0.8,
    "required_claim_score": 0.6,
    "limitation_score": 0.5,
    "forbidden_overclaim_violations": 0,
}
_SPACE_RE = re.compile(r"\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a collection-level research-objective prediction against "
            "a manual expert target."
        )
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET_PATH,
        help="Manual research-objective target JSON.",
    )
    parser.add_argument(
        "--prediction",
        type=Path,
        required=True,
        help="System prediction JSON using the research-objective target shape.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Destination report JSON.",
    )
    parser.add_argument(
        "--quality-gate",
        action="store_true",
        help="Exit non-zero when the target quality gate fails.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report_path = evaluate_research_objective_target(
        target_path=args.target,
        prediction_path=args.prediction,
        output_path=args.report,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.quality_gate and report["quality_gate"]["status"] == "fail":
        raise SystemExit(1)


def evaluate_research_objective_target(
    *,
    target_path: str | Path = DEFAULT_TARGET_PATH,
    prediction_path: str | Path,
    output_path: str | Path = DEFAULT_REPORT_PATH,
) -> Path:
    target = _read_json(Path(target_path))
    prediction = _read_json(Path(prediction_path))
    report = evaluate_target_prediction(target=target, prediction=prediction)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def evaluate_target_prediction(
    *,
    target: dict[str, Any],
    prediction: dict[str, Any],
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    validation_errors = validate_target(target)
    prediction_text = _flatten_text(prediction)
    scope = _evaluate_evidence_scope(
        target.get("expected_evidence_scope"),
        prediction.get("evidence_scope"),
    )
    paper_contributions = _evaluate_paper_contributions(
        target.get("required_paper_contributions"),
        prediction.get("paper_contributions"),
        prediction_text,
    )
    required_claims = _evaluate_required_claims(
        target.get("required_claims"),
        prediction_text,
    )
    mechanism_chains = _evaluate_mechanism_chains(
        target.get("required_mechanism_chains"),
        prediction_text,
    )
    limitations = _evaluate_limitations(
        target.get("required_limitations"),
        prediction_text,
    )
    forbidden = _evaluate_forbidden_overclaims(
        target.get("forbidden_overclaims"),
        prediction_text,
    )
    scores = {
        "evidence_scope_score": scope["score"],
        "paper_contribution_score": paper_contributions["score"],
        "required_claim_score": required_claims["score"],
        "mechanism_chain_score": mechanism_chains["score"],
        "limitation_score": limitations["score"],
        "forbidden_overclaim_violations": len(forbidden["violations"]),
    }
    return {
        "target_id": target.get("target_id"),
        "schema_version": "research_objective_target_report.v1",
        "validation_errors": validation_errors,
        "scores": scores,
        "evidence_scope": scope,
        "paper_contributions": paper_contributions,
        "required_claims": required_claims,
        "mechanism_chains": mechanism_chains,
        "limitations": limitations,
        "forbidden_overclaims": forbidden,
        "quality_gate": evaluate_quality_gate(
            scores,
            thresholds=thresholds or DEFAULT_QUALITY_THRESHOLDS,
            validation_errors=validation_errors,
        ),
    }


def validate_target(target: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in (
        "target_id",
        "objective",
        "expected_evidence_scope",
        "required_paper_contributions",
        "required_claims",
        "required_limitations",
        "forbidden_overclaims",
    ):
        if key not in target:
            errors.append(f"missing_target_key:{key}")
    if not isinstance(target.get("objective"), dict):
        errors.append("objective_must_be_object")
    if not isinstance(target.get("expected_evidence_scope"), dict):
        errors.append("expected_evidence_scope_must_be_object")
    for key, value in (target.get("expected_evidence_scope") or {}).items():
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"expected_evidence_scope_value_must_be_int:{key}")
    for claim in target.get("required_claims") or []:
        if not isinstance(claim, dict):
            errors.append("required_claim_must_be_object")
            continue
        for key in ("claim_id", "text", "required_papers"):
            if not claim.get(key):
                errors.append(f"required_claim_missing_{key}")
    return errors


def evaluate_quality_gate(
    scores: dict[str, float],
    *,
    thresholds: dict[str, float],
    validation_errors: list[str],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if validation_errors:
        checks.append(
            {
                "status": "fail",
                "metric": "target_validation",
                "actual": len(validation_errors),
                "maximum": 0,
            }
        )
    for metric, threshold in thresholds.items():
        actual = scores.get(metric)
        if metric == "forbidden_overclaim_violations":
            passed = actual == threshold
            check = {
                "status": "pass" if passed else "fail",
                "metric": metric,
                "actual": actual,
                "maximum": threshold,
            }
        else:
            passed = actual is not None and actual >= threshold
            check = {
                "status": "pass" if passed else "fail",
                "metric": metric,
                "actual": actual,
                "minimum": threshold,
            }
        checks.append(check)
    failed_checks = [check for check in checks if check["status"] == "fail"]
    return {
        "status": "fail" if failed_checks else "pass",
        "checks": checks,
        "failed_checks": failed_checks,
    }


def _evaluate_evidence_scope(
    expected: Any,
    actual: Any,
) -> dict[str, Any]:
    expected_scope = expected if isinstance(expected, dict) else {}
    actual_scope = actual if isinstance(actual, dict) else {}
    checks = []
    for key, expected_value in expected_scope.items():
        actual_value = actual_scope.get(key)
        matched = (
            not isinstance(actual_value, bool)
            and isinstance(actual_value, (int, float))
            and actual_value >= expected_value
        )
        checks.append(
            {
                "metric": key,
                "expected_minimum": expected_value,
                "actual": actual_value,
                "status": "pass" if matched else "fail",
            }
        )
    return _scored_checks(checks)


def _evaluate_paper_contributions(
    expected: Any,
    actual: Any,
    prediction_text: str,
) -> dict[str, Any]:
    expected_items = expected if isinstance(expected, list) else []
    actual_items = actual if isinstance(actual, list) else []
    actual_by_paper_id = {
        str(item.get("paper_id") or ""): item
        for item in actual_items
        if isinstance(item, dict)
    }
    checks = []
    for item in expected_items:
        if not isinstance(item, dict):
            continue
        paper_id = str(item.get("paper_id") or "")
        contribution_text = _flatten_text(actual_by_paper_id.get(paper_id) or {})
        search_text = contribution_text or prediction_text
        required_terms = _list_of_strings(item.get("required_terms"))
        matched_terms = _matched_values(required_terms, search_text)
        minimum = max(1, len(required_terms) // 2) if required_terms else 1
        matched = bool(contribution_text) and len(matched_terms) >= minimum
        checks.append(
            {
                "paper_id": paper_id,
                "status": "pass" if matched else "fail",
                "matched_terms": matched_terms,
                "missing_terms": [
                    term for term in required_terms if term not in matched_terms
                ],
                "required_term_count": len(required_terms),
            }
        )
    return _scored_checks(checks)


def _evaluate_required_claims(expected: Any, prediction_text: str) -> dict[str, Any]:
    checks = []
    for claim in expected if isinstance(expected, list) else []:
        if not isinstance(claim, dict):
            continue
        required_terms = _list_of_strings(claim.get("required_terms"))
        required_numbers = _list_of_strings(claim.get("required_numbers"))
        required_values = [*required_terms, *required_numbers]
        matched_values = _matched_values(required_values, prediction_text)
        matched = bool(required_values) and len(matched_values) == len(required_values)
        checks.append(
            {
                "claim_id": claim.get("claim_id"),
                "status": "pass" if matched else "fail",
                "matched_values": matched_values,
                "missing_values": [
                    value for value in required_values if value not in matched_values
                ],
                "required_value_count": len(required_values),
            }
        )
    return _scored_checks(checks)


def _evaluate_mechanism_chains(expected: Any, prediction_text: str) -> dict[str, Any]:
    checks = []
    for chain in expected if isinstance(expected, list) else []:
        if not isinstance(chain, dict):
            continue
        path_values = _list_of_strings(chain.get("path"))
        matched_values = _matched_values(path_values, prediction_text)
        matched = bool(path_values) and len(matched_values) == len(path_values)
        checks.append(
            {
                "chain_id": chain.get("chain_id"),
                "status": "pass" if matched else "fail",
                "matched_values": matched_values,
                "missing_values": [
                    value for value in path_values if value not in matched_values
                ],
            }
        )
    return _scored_checks(checks)


def _evaluate_limitations(expected: Any, prediction_text: str) -> dict[str, Any]:
    checks = []
    for limitation in expected if isinstance(expected, list) else []:
        if not isinstance(limitation, dict):
            continue
        limitation_text = str(limitation.get("text") or "")
        matched = _text_matches(limitation_text, prediction_text)
        checks.append(
            {
                "limitation_id": limitation.get("limitation_id"),
                "paper_id": limitation.get("paper_id"),
                "status": "pass" if matched else "fail",
                "missing_text": None if matched else limitation_text,
            }
        )
    return _scored_checks(checks)


def _evaluate_forbidden_overclaims(expected: Any, prediction_text: str) -> dict[str, Any]:
    violations = []
    for overclaim in expected if isinstance(expected, list) else []:
        if not isinstance(overclaim, dict):
            continue
        text = str(overclaim.get("text") or "")
        if _text_matches(text, prediction_text):
            violations.append(
                {
                    "overclaim_id": overclaim.get("overclaim_id"),
                    "text": text,
                }
            )
    return {
        "violations": violations,
        "violation_count": len(violations),
    }


def _scored_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [check for check in checks if check.get("status") == "pass"]
    score = round(len(passed) / len(checks), 4) if checks else 0.0
    return {
        "score": score,
        "matched_count": len(passed),
        "total_count": len(checks),
        "checks": checks,
        "failed_checks": [check for check in checks if check.get("status") == "fail"],
    }


def _matched_values(values: list[str], text: str) -> list[str]:
    return [value for value in values if _text_matches(value, text)]


def _text_matches(needle: str, haystack: str) -> bool:
    normalized_needle = _normalize_text(needle)
    if not normalized_needle:
        return False
    return normalized_needle in haystack


def _flatten_text(value: Any) -> str:
    pieces: list[str] = []
    _collect_text(value, pieces)
    return _normalize_text(" ".join(pieces))


def _collect_text(value: Any, pieces: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            pieces.append(str(key))
            _collect_text(item, pieces)
    elif isinstance(value, list):
        for item in value:
            _collect_text(item, pieces)
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        pieces.append(str(value))


def _normalize_text(value: str) -> str:
    text = value.casefold()
    replacements = {
        "°": "",
        "℃": " c",
        "μ": "u",
        "µ": "u",
        "ω": "ohm",
        "Ω": "ohm",
        "×": "x",
        "–": "-",
        "—": "-",
        "·": " ",
        "−": "-",
        "^": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", text)
    text = re.sub(r"[^a-z0-9.%/+-]+", " ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _list_of_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


if __name__ == "__main__":
    main()
