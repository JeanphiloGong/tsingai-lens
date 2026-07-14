#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from application.evaluation.research_understanding_review_import_service import (
    confirm_agent_review_rows,
)


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
    confirmed = confirm_agent_review_rows(rows)
    for row in confirmed:
        if row.get("action") == "__agent_review_error__":
            raise ValueError(str(row.get("agent_review_error")))
    return confirmed


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


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


if __name__ == "__main__":
    main()
