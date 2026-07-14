#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


RECOMMENDATIONS = {"accept", "reject", "correct", "skip", "unclear"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert human-confirmed agent_review suggestions into an importable "
            "Lens review decision JSONL file. Rows without "
            "agent_review.human_confirmed=true remain action=skip."
        )
    )
    parser.add_argument("input_path", help="Agent-reviewed JSONL file.")
    parser.add_argument(
        "--output-path",
        "-o",
        help="Output JSONL path. Defaults to stdout.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = confirm_agent_review_decisions(read_jsonl(Path(args.input_path)))
    output = _jsonl(rows)
    if args.output_path:
        Path(args.output_path).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)


def confirm_agent_review_decisions(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [_confirmed_row(row, line_number=index + 1) for index, row in enumerate(rows)]


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


def _confirmed_row(row: dict[str, Any], *, line_number: int) -> dict[str, Any]:
    output = dict(row)
    output["action"] = "skip"
    review = _mapping(row.get("agent_review"))
    if not bool(review.get("human_confirmed")):
        return output
    recommendation = _text(review.get("recommendation")).lower()
    if recommendation not in RECOMMENDATIONS:
        raise ValueError(
            f"line {line_number}: agent_review.recommendation is not supported"
        )
    if recommendation in {"skip", "unclear"}:
        return output
    if recommendation == "accept":
        _validate_accept(output, line_number=line_number)
        output["action"] = "accept"
        output["expert_note"] = _confirmed_note(output, review)
        return output
    if recommendation == "reject":
        issue_type = _text(review.get("issue_type")).lower()
        if not issue_type:
            raise ValueError(
                f"line {line_number}: confirmed reject requires issue_type"
            )
        output["action"] = "reject"
        output["issue_type"] = issue_type
        output["expert_note"] = _confirmed_note(output, review)
        return output
    target = _mapping(review.get("suggested_target"))
    if not _text(target.get("statement")):
        raise ValueError(
            f"line {line_number}: confirmed correct requires suggested_target.statement"
        )
    evidence_ref_ids = _strings(target.get("evidence_ref_ids"))
    if not evidence_ref_ids:
        raise ValueError(
            f"line {line_number}: confirmed correct requires evidence_ref_ids"
        )
    output["action"] = "correct"
    output["suggested_target"] = target
    output["curated_evidence_ref_ids"] = evidence_ref_ids
    output["expert_note"] = _confirmed_note(output, review)
    return output


def _validate_accept(row: dict[str, Any], *, line_number: int) -> None:
    gate = _mapping(row.get("acceptance_gate"))
    blocking = _strings(gate.get("blocking_missing")) or _strings(
        row.get("protocol_blocking_missing")
    )
    if not bool(gate.get("accept_allowed")) or blocking:
        raise ValueError(
            f"line {line_number}: confirmed accept is blocked by acceptance_gate"
        )


def _confirmed_note(row: dict[str, Any], review: dict[str, Any]) -> str:
    note = _text(review.get("note"))
    existing = _text(row.get("expert_note"))
    return existing or note or "Human confirmed agent review suggestion."


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    return [_text(item) for item in value if _text(item)] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


if __name__ == "__main__":
    main()
