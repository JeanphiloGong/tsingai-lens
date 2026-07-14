#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import explicit human expert decisions from review-jsonl rows into "
            "research-understanding feedback or curation records."
        )
    )
    parser.add_argument("input_path", help="JSONL file with reviewed candidate rows.")
    parser.add_argument(
        "--reviewer",
        required=True,
        help="Human reviewer id or email. AI/agent reviewer ids are rejected.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and summarize decisions without writing feedback records.",
    )
    parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        help=(
            "Fail when accepted or corrected rows still carry risky review "
            "warnings, such as paper-level or table-row checks."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = import_review_decisions(
        input_path=Path(args.input_path),
        reviewer=args.reviewer,
        dry_run=args.dry_run,
        fail_on_warnings=args.fail_on_warnings,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "fail":
        raise SystemExit(1)


def import_review_decisions(
    *,
    input_path: Path,
    reviewer: str,
    dry_run: bool = False,
    fail_on_warnings: bool = False,
    feedback_service=None,
) -> dict:
    backend_root = str(DEFAULT_BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from application.evaluation import (  # noqa: PLC0415
        ResearchUnderstandingReviewImportService,
    )

    service = ResearchUnderstandingReviewImportService(feedback_service)
    return service.import_jsonl_file(
        input_path=input_path,
        reviewer=reviewer,
        dry_run=dry_run,
        fail_on_warnings=fail_on_warnings,
    )


if __name__ == "__main__":
    main()
