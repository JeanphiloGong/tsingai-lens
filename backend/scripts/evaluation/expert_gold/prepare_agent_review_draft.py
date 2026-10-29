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

from application.evaluation.finding_feedback_service import parse_curated_finding


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
        "curated_finding": _curated_finding(draft),
    }
    return draft


def _initial_note(row: dict[str, Any]) -> str:
    checks = ((row.get("acceptance_gate") or {}).get("review_checks") or [])
    blockers = (row.get("protocol_blocking_missing") or [])
    bits = []
    if checks:
        bits.append("Verify before recommending: " + "; ".join(checks))
    if blockers:
        bits.append("Protocol draft is missing: " + ", ".join(blockers))
    if not bits:
        bits.append("Review the Finding, factors, outcome, attribution, and Evidence.")
    return " ".join(bits)


def _curated_finding(row: dict[str, Any]) -> dict[str, Any]:
    target = (
        (row.get("curated_finding") or {})
        or (row.get("training_target") or {})
        or (row.get("system_prediction") or {})
    )
    if not target:
        raise ValueError("decision row requires one complete canonical Finding")
    parse_curated_finding(target)
    return target


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






def _text(value: str | None) -> str:
    return value.strip() if value is not None else ""


if __name__ == "__main__":
    main()
