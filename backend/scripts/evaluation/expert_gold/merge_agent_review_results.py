#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


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
    reviews = _agent_reviews_by_finding_id(agent_rows)
    merged = []
    for row in decision_rows:
        finding_id = _text(row.get("finding_id"))
        output = dict(row)
        output["action"] = "skip"
        if finding_id in reviews:
            output["agent_review"] = reviews[finding_id]
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


def _agent_reviews_by_finding_id(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    reviews: dict[str, dict[str, Any]] = {}
    for line_number, row in enumerate(rows, start=1):
        finding_id = _text(row.get("finding_id"))
        if not finding_id:
            raise ValueError(f"line {line_number}: finding_id is required")
        if finding_id in reviews:
            raise ValueError(f"line {line_number}: duplicate finding_id {finding_id}")
        review = _validated_agent_review(row, line_number=line_number)
        reviews[finding_id] = review
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
    suggested_target = _mapping(review.get("suggested_target"))
    if suggested_target:
        output["suggested_target"] = suggested_target
    return {key: value for key, value in output.items() if value not in ("", {}, [])}


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
