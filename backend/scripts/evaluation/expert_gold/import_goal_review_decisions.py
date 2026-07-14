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
            "warnings without expert_note, such as paper-level or table-row checks."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format. JSON is stable for automation; text is for expert review loops.",
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
    if args.format == "text":
        print(render_text_summary(summary))
    else:
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


def render_text_summary(summary: dict) -> str:
    mode = "dry-run" if summary.get("dry_run") else "import"
    lines = [
        f"Review decision import: {summary.get('status', 'unknown')} ({mode})",
        (
            "Rows: "
            f"total={summary.get('total_rows', 0)} "
            f"written={summary.get('written_count', 0)} "
            f"skipped={summary.get('skipped_count', 0)}"
        ),
    ]
    counts = summary.get("counts")
    if isinstance(counts, dict) and counts:
        lines.append(
            "Decisions: "
            + ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
        )
    progress = summary.get("review_progress")
    if isinstance(progress, dict):
        lines.append(
            "Review progress: "
            f"actionable={progress.get('actionable_count', 0)} "
            f"needs_review={progress.get('needs_review_count', 0)} "
            f"ready_to_write={bool(progress.get('ready_to_write'))}"
        )
        next_steps = progress.get("next_steps")
        if isinstance(next_steps, list) and next_steps:
            lines.append("Next steps:")
            lines.extend(f"- {step}" for step in next_steps)
    warnings = summary.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append(f"Warnings: {len(warnings)}")
        lines.extend(
            "- "
            + _line_ref(warning)
            + str(warning.get("message", ""))
            for warning in warnings[:5]
            if isinstance(warning, dict)
        )
    errors = summary.get("errors")
    if isinstance(errors, list) and errors:
        lines.append(f"Errors: {len(errors)}")
        lines.extend(
            "- "
            + _line_ref(error)
            + str(error.get("message", ""))
            for error in errors[:5]
            if isinstance(error, dict)
        )
    affected_goals = summary.get("affected_goals")
    if isinstance(affected_goals, list) and affected_goals:
        lines.append("Affected goals:")
        for goal in affected_goals:
            if isinstance(goal, dict):
                lines.extend(_render_goal_summary(goal))
    else:
        lines.append("Affected goals: none")
    readiness = summary.get("readiness_summary")
    if isinstance(readiness, dict) and readiness:
        lines.extend(_render_readiness_summary(readiness))
    return "\n".join(lines)


def _render_readiness_summary(readiness: dict) -> list[str]:
    return [
        "Readiness after import:",
        (
            "- "
            f"goals={readiness.get('goal_count', 0)} "
            f"training_ready_goals={readiness.get('projected_training_ready_goal_count', 0)} "
            f"message_ready_goals={readiness.get('projected_training_message_goal_count', 0)} "
            f"protocol_ready_goals={readiness.get('projected_protocol_ready_goal_count', 0)}"
        ),
        (
            "- "
            f"remaining_review_candidates={readiness.get('projected_review_candidate_count', 0)} "
            f"rejected={readiness.get('projected_rejected_count', 0)}"
        ),
        (
            "- "
            f"ready_for_training_export={bool(readiness.get('ready_for_training_export'))} "
            f"ready_for_protocol_drafting={bool(readiness.get('ready_for_protocol_drafting'))}"
        ),
    ]


def _render_goal_summary(goal: dict) -> list[str]:
    collection_id = goal.get("collection_id", "")
    goal_id = goal.get("goal_id", "")
    lines = [
        f"- {collection_id}/{goal_id}",
        (
            "  now: "
            f"training_ready={goal.get('training_ready_count', 0)} "
            f"training_messages={goal.get('training_message_count', 0)} "
            f"protocol_ready={goal.get('protocol_ready_count', 0)} "
            f"review_candidates={goal.get('review_candidate_count', 0)} "
            f"rejected={goal.get('rejected_count', 0)}"
        ),
        (
            "  pending: "
            f"accept={goal.get('pending_accept_count', 0)} "
            f"correct={goal.get('pending_correct_count', 0)} "
            f"reject={goal.get('pending_reject_count', 0)}"
        ),
        (
            "  after import: "
            f"training_ready={goal.get('projected_training_ready_count', 0)} "
            f"training_messages={goal.get('projected_training_message_count', 0)} "
            f"protocol_ready={goal.get('projected_protocol_ready_count', 0)} "
            f"review_candidates={goal.get('projected_review_candidate_count', 0)} "
            f"rejected={goal.get('projected_rejected_count', 0)}"
        ),
    ]
    next_review = goal.get("next_review_finding_id")
    if next_review:
        lines.append(f"  next_review_finding_id={next_review}")
    issues = goal.get("readiness_issues")
    if isinstance(issues, list) and issues:
        lines.append(f"  readiness issues: {len(issues)} shown")
        for issue in issues[:3]:
            if isinstance(issue, dict):
                missing = []
                training = issue.get("missing_training_message")
                protocol = issue.get("missing_protocol_input")
                if isinstance(training, list) and training:
                    missing.append("training=" + ",".join(str(item) for item in training))
                if isinstance(protocol, list) and protocol:
                    missing.append("protocol=" + ",".join(str(item) for item in protocol))
                lines.append(
                    "  - "
                    f"{issue.get('finding_id', '')}: "
                    + ("; ".join(missing) if missing else "missing readiness details")
                )
    return lines


def _line_ref(row: dict) -> str:
    line = row.get("line")
    if line:
        return f"line {line}: "
    return ""


if __name__ == "__main__":
    main()
