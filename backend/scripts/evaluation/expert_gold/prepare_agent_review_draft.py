#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_REVIEWER = "ai-reviewer-codex"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a safe agent-review JSONL draft from a Lens decision-template. "
            "The output keeps action=skip so no agent suggestion can be imported "
            "as an expert label without human confirmation."
        )
    )
    parser.add_argument("input_path", help="Decision-template JSONL file.")
    parser.add_argument(
        "--output-path",
        "-o",
        help="Output JSONL path. Defaults to stdout.",
    )
    parser.add_argument(
        "--reviewer",
        default=DEFAULT_REVIEWER,
        help="Agent reviewer id. Must start with ai-reviewer or agent-.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = prepare_agent_review_draft(
        read_jsonl(Path(args.input_path)),
        reviewer=args.reviewer,
    )
    output = _jsonl(rows)
    if args.output_path:
        Path(args.output_path).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)


def prepare_agent_review_draft(
    rows: list[dict[str, Any]],
    *,
    reviewer: str = DEFAULT_REVIEWER,
) -> list[dict[str, Any]]:
    reviewer = _agent_reviewer(reviewer)
    return [_draft_row(row, reviewer=reviewer) for row in rows]


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


def _draft_row(row: dict[str, Any], *, reviewer: str) -> dict[str, Any]:
    draft = dict(row)
    draft["action"] = "skip"
    draft["agent_review"] = {
        "reviewer": reviewer,
        "recommendation": "unclear",
        "issue_type": "",
        "note": _initial_note(draft),
        "suggested_target": _suggested_target(draft),
    }
    return draft


def _initial_note(row: dict[str, Any]) -> str:
    checks = _strings(_mapping(row.get("acceptance_gate")).get("review_checks"))
    blockers = _strings(row.get("protocol_blocking_missing"))
    bits = []
    if checks:
        bits.append("Verify before recommending: " + "; ".join(checks))
    if blockers:
        bits.append("Protocol draft is missing: " + ", ".join(blockers))
    if not bits:
        bits.append("Review the finding, variables, direction, scope, and evidence.")
    return " ".join(bits)


def _suggested_target(row: dict[str, Any]) -> dict[str, Any]:
    target = _mapping(row.get("suggested_target"))
    if not target:
        target = {
            "statement": _text(row.get("statement")),
            "variables": _strings(row.get("variables")),
            "outcomes": _strings(row.get("outcomes")),
            "direction": _text(row.get("direction")),
            "evidence_ref_ids": _strings(row.get("curated_evidence_ref_ids")),
        }
    return {
        key: value
        for key, value in target.items()
        if value not in ("", [], {}, None)
    }


def _agent_reviewer(value: str) -> str:
    reviewer = _text(value)
    if not (
        reviewer.lower().startswith("ai-reviewer")
        or reviewer.lower().startswith("agent-")
    ):
        raise ValueError("reviewer must start with ai-reviewer or agent-")
    return reviewer


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
