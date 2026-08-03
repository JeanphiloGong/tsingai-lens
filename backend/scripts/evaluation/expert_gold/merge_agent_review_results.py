#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from domain.core import Finding  # noqa: E402


RECOMMENDATIONS = {"accept", "reject", "correct", "unclear", "skip"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge independent agent_review results into a Lens decision-template "
            "JSONL file. Output rows keep action=skip and human_confirmed=false."
        )
    )
    parser.add_argument("decision_template_path", help="Original decision-template JSONL.")
    parser.add_argument("agent_review_path", help="Agent review result JSONL.")
    parser.add_argument(
        "--output-path",
        "-o",
        help="Output JSONL path. Defaults to stdout.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = merge_agent_review_results(
        decision_rows=read_jsonl(Path(args.decision_template_path)),
        agent_rows=read_jsonl(Path(args.agent_review_path)),
    )
    output = _jsonl(rows)
    if args.output_path:
        Path(args.output_path).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)


def merge_agent_review_results(
    *,
    decision_rows: list[dict[str, Any]],
    agent_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reviews = _agent_reviews_by_identity(agent_rows)
    merged = []
    for row in decision_rows:
        identity = _identity(row)
        output = dict(row)
        output["action"] = "skip"
        if identity in reviews:
            output["agent_review"] = reviews[identity]
        merged.append(output)
    return merged


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number} must be a JSON object")
            rows.append(payload)
    return rows


def _agent_reviews_by_identity(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    reviews: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for line_number, row in enumerate(rows, start=1):
        try:
            identity = _identity(row)
        except ValueError as exc:
            raise ValueError(f"line {line_number}: {exc}") from exc
        if identity in reviews:
            raise ValueError(f"line {line_number}: duplicate Finding identity")
        review = _validated_agent_review(row, line_number=line_number)
        reviews[identity] = review
    return reviews


def _validated_agent_review(
    row: dict[str, Any],
    *,
    line_number: int,
) -> dict[str, Any]:
    review = _mapping(row.get("agent_review")) or _mapping(row)
    reviewer = _text(review.get("reviewer"))
    if not _is_agent_reviewer(reviewer):
        raise ValueError(
            f"line {line_number}: agent_review.reviewer must start with ai-reviewer or agent-"
        )
    recommendation = _text(review.get("recommendation")).lower()
    if recommendation not in RECOMMENDATIONS:
        raise ValueError(
            f"line {line_number}: agent_review.recommendation is not supported"
        )
    output = {
        "reviewer": reviewer,
        "recommendation": recommendation,
        "issue_type": _text(review.get("issue_type")),
        "note": _text(review.get("note")),
        "human_confirmed": False,
    }
    curated_finding = _mapping(review.get("curated_finding"))
    if curated_finding:
        finding = Finding.from_mapping(curated_finding)
        if finding.to_record() != curated_finding:
            raise ValueError(
                f"line {line_number}: agent_review.curated_finding is not canonical"
            )
        output["curated_finding"] = finding.to_record()
    return {key: value for key, value in output.items() if value not in ("", {}, [])}


def _identity(row: dict[str, Any]) -> tuple[str, str, int, str]:
    try:
        analysis_version = int(row.get("analysis_version") or 0)
    except (TypeError, ValueError):
        analysis_version = 0
    identity = (
        _text(row.get("collection_id")),
        _text(row.get("objective_id")),
        analysis_version,
        _text(row.get("finding_id")),
    )
    if not identity[0] or not identity[1] or identity[2] < 1 or not identity[3]:
        raise ValueError(
            "collection_id, objective_id, analysis_version, and finding_id are required"
        )
    return identity


def _is_agent_reviewer(value: str) -> bool:
    normalized = value.lower()
    return normalized.startswith("ai-reviewer") or normalized.startswith("agent-")


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


if __name__ == "__main__":
    main()
