#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import human decisions for versioned Objective Findings."
    )
    parser.add_argument("input_path", type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument(
        "--user-id", required=True, help="Owner of the reviewed collections."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    return parser.parse_args()


async def import_review_decisions(
    *,
    input_path: Path,
    reviewer: str,
    user_id: str,
    dry_run: bool = False,
    feedback_service=None,
) -> dict:
    backend_root = str(DEFAULT_BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from application.evaluation import (
        FindingReviewImportService,
        finding_feedback_service,
    )

    engine = None
    if feedback_service is None:
        from infra.persistence.database import (  # noqa: PLC0415
            AsyncSessionLocal,
            DatabaseSettings,
            build_database_engine,
        )

        engine = build_database_engine(DatabaseSettings())
        AsyncSessionLocal.configure(bind=engine)

        feedback_service = finding_feedback_service
    try:
        return await FindingReviewImportService(feedback_service).import_jsonl_file(
            input_path=input_path,
            reviewer=reviewer,
            user_id=user_id,
            dry_run=dry_run,
        )
    finally:
        if engine is not None:
            await engine.dispose()


def render_text_summary(summary: dict) -> str:
    mode = "dry-run" if summary.get("dry_run") else "import"
    lines = [
        f"Finding review import: {summary.get('status', 'unknown')} ({mode})",
        (
            f"Rows: total={summary.get('total_rows', 0)} "
            f"written={summary.get('written_count', 0)} "
            f"skipped={summary.get('skipped_count', 0)}"
        ),
    ]
    counts = summary.get("counts") or {}
    if counts:
        lines.append(
            "Decisions: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
        )
    for error in summary.get("errors") or []:
        lines.append(f"Error line {error.get('line')}: {error.get('message')}")
    return "\n".join(lines)


async def main_async() -> None:
    args = parse_args()
    summary = await import_review_decisions(
        input_path=args.input_path,
        reviewer=args.reviewer,
        user_id=args.user_id,
        dry_run=args.dry_run,
    )
    print(
        render_text_summary(summary)
        if args.format == "text"
        else json.dumps(summary, ensure_ascii=False, indent=2)
    )
    if summary["status"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main_async())
