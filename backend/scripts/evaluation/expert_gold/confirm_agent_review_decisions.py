#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
REVIEW_IMPORT_SERVICE_PATH = (
    DEFAULT_BACKEND_ROOT
    / "application"
    / "evaluation"
    / "research_understanding_review_import_service.py"
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
    confirm_agent_review_rows = _load_confirm_agent_review_rows()
    confirmed = confirm_agent_review_rows(rows)
    for row in confirmed:
        if row.get("action") == "__agent_review_error__":
            raise ValueError(str(row.get("agent_review_error")))
    return confirmed


def _load_confirm_agent_review_rows():
    backend_root = str(DEFAULT_BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    spec = importlib.util.spec_from_file_location(
        "research_understanding_review_import_service_for_agent_confirmation",
        REVIEW_IMPORT_SERVICE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {REVIEW_IMPORT_SERVICE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.confirm_agent_review_rows


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
