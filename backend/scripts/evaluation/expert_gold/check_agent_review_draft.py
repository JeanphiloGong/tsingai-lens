#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


AGENT_RECOMMENDATIONS = ("accept", "reject", "correct", "unclear", "skip")
REJECT_ISSUE_OPTIONS = (
    "evidence_not_grounded",
    "missing_evidence",
    "insufficient_evidence",
    "wrong_variable",
    "wrong_outcome",
    "wrong_direction",
    "wrong_context",
    "wrong_relation",
    "overclaim",
    "unclear_statement",
    "other",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an AI/agent review draft without importing labels. Rows "
            "must keep action=skip; agent recommendations live under agent_review."
        )
    )
    parser.add_argument("input_path", help="JSONL decision-template file reviewed by an agent.")
    parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        help="Exit non-zero when the draft still needs human attention warnings.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = check_agent_review_draft(
        Path(args.input_path),
        fail_on_warnings=args.fail_on_warnings,
    )
    if args.format == "text":
        print(render_text_summary(summary))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "fail":
        raise SystemExit(1)


def check_agent_review_draft(
    input_path: Path,
    *,
    fail_on_warnings: bool = False,
) -> dict[str, Any]:
    rows = read_jsonl(input_path)
    row_results = [
        _check_row(row, line_number=index + 1) for index, row in enumerate(rows)
    ]
    errors = [
        issue
        for result in row_results
        for issue in result["errors"]
    ]
    warnings = [
        issue
        for result in row_results
        for issue in result["warnings"]
    ]
    counts = _recommendation_counts(row_results)
    agent_reviewed_count = sum(
        value for key, value in counts.items() if key not in {"skip", "missing"}
    )
    if agent_reviewed_count == 0:
        warnings.append(
            {
                "line": 0,
                "finding_id": "",
                "message": "no_agent_recommendations: all rows are unreviewed or skip",
            }
        )
    status = "fail" if errors or (fail_on_warnings and warnings) else "pass"
    return {
        "status": status,
        "total_rows": len(rows),
        "agent_reviewed_count": agent_reviewed_count,
        "counts": counts,
        "goals": _goal_handoff(row_results),
        "errors": errors,
        "warnings": warnings,
        "human_handoff": {
            "ready_for_human_review": status == "pass",
            "required_action": (
                "Human expert must verify agent_review recommendations, then "
                "copy accepted decisions into action before import."
            ),
            "import_guard": "Rows remain action=skip; this checker writes no labels.",
        },
    }


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


def render_text_summary(summary: dict[str, Any]) -> str:
    lines = [
        f"Agent review draft: {summary['status']}",
        f"Rows: {summary['total_rows']}",
        f"Reviewed by agent: {summary['agent_reviewed_count']}",
    ]
    counts = _mapping(summary.get("counts"))
    if counts:
        lines.append(
            "Recommendations: "
            + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        )
    errors = _mapping_list(summary.get("errors"))
    if errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(
            f"- line {item['line']}: {item['message']}" for item in errors
        )
    warnings = _mapping_list(summary.get("warnings"))
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(
            f"- line {item['line']}: {item['message']}" for item in warnings
        )
    handoff = _mapping(summary.get("human_handoff"))
    if handoff:
        lines.append("")
        lines.append(str(handoff.get("required_action") or ""))
    goals = _mapping_list(summary.get("goals"))
    if goals:
        lines.append("")
        lines.append("Goal handoff:")
        for goal in goals:
            lines.append(
                "- "
                f"{goal.get('goal_id') or 'n/a'}: "
                f"reviewed={goal.get('agent_reviewed_count', 0)} "
                f"accept={goal.get('accept_count', 0)} "
                f"reject={goal.get('reject_count', 0)} "
                f"correct={goal.get('correct_count', 0)} "
                f"unclear={goal.get('unclear_count', 0)} "
                f"next={goal.get('next_action') or 'n/a'}"
            )
    return "\n".join(lines)


def _check_row(row: dict[str, Any], *, line_number: int) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    finding_id = _text(row.get("finding_id"))
    action = _text(row.get("action")).lower()
    if action != "skip":
        errors.append(
            _issue(
                line_number,
                finding_id,
                "agent drafts must keep action=skip; human review sets import actions",
            )
        )
    agent_review = _mapping(row.get("agent_review"))
    if not agent_review:
        warnings.append(_issue(line_number, finding_id, "missing agent_review"))
        return {
            "collection_id": _text(row.get("collection_id")),
            "goal_id": _text(row.get("goal_id")),
            "finding_id": finding_id,
            "recommendation": "missing",
            "errors": errors,
            "warnings": warnings,
        }
    reviewer = _text(agent_review.get("reviewer"))
    if not _is_agent_reviewer(reviewer):
        errors.append(
            _issue(
                line_number,
                finding_id,
                "agent_review.reviewer must start with ai-reviewer or agent-",
            )
        )
    recommendation = _text(agent_review.get("recommendation")).lower()
    if recommendation not in AGENT_RECOMMENDATIONS:
        errors.append(
            _issue(
                line_number,
                finding_id,
                "agent_review.recommendation must be accept, reject, correct, unclear, or skip",
            )
        )
    elif recommendation == "accept":
        _check_accept_recommendation(
            row,
            line_number=line_number,
            finding_id=finding_id,
            errors=errors,
            warnings=warnings,
        )
    elif recommendation == "reject":
        issue_type = _text(agent_review.get("issue_type")).lower()
        if issue_type not in REJECT_ISSUE_OPTIONS:
            errors.append(
                _issue(
                    line_number,
                    finding_id,
                    "agent reject recommendation requires a valid issue_type",
                )
            )
    elif recommendation == "correct":
        target = _mapping(agent_review.get("suggested_target"))
        if not _text(target.get("statement")):
            errors.append(
                _issue(
                    line_number,
                    finding_id,
                    "agent correct recommendation requires agent_review.suggested_target.statement",
                )
            )
        if not _strings(target.get("evidence_ref_ids")):
            errors.append(
                _issue(
                    line_number,
                    finding_id,
                    "agent correct recommendation requires evidence_ref_ids",
                )
            )
    if recommendation in {"accept", "reject", "correct", "unclear"} and not _text(
        agent_review.get("note")
    ):
        warnings.append(
            _issue(
                line_number,
                finding_id,
                "agent reviewed row should include agent_review.note",
            )
        )
    if not _mapping_list(row.get("evidence")):
        warnings.append(_issue(line_number, finding_id, "row has no evidence summary"))
    return {
        "collection_id": _text(row.get("collection_id")),
        "goal_id": _text(row.get("goal_id")),
        "finding_id": finding_id,
        "recommendation": recommendation or "missing",
        "errors": errors,
        "warnings": warnings,
    }


def _goal_handoff(row_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    goals: dict[tuple[str, str], dict[str, Any]] = {}
    for result in row_results:
        key = (_text(result.get("collection_id")), _text(result.get("goal_id")))
        goal = goals.setdefault(
            key,
            {
                "collection_id": key[0],
                "goal_id": key[1],
                "total_rows": 0,
                "agent_reviewed_count": 0,
                "accept_count": 0,
                "reject_count": 0,
                "correct_count": 0,
                "unclear_count": 0,
                "skip_count": 0,
                "missing_count": 0,
                "first_unresolved_finding_id": "",
            },
        )
        recommendation = _text(result.get("recommendation")) or "missing"
        goal["total_rows"] += 1
        if recommendation in {"accept", "reject", "correct", "unclear"}:
            goal["agent_reviewed_count"] += 1
        count_key = f"{recommendation}_count"
        if count_key in goal:
            goal[count_key] += 1
        if recommendation in {"missing", "skip", "unclear"} and not goal[
            "first_unresolved_finding_id"
        ]:
            goal["first_unresolved_finding_id"] = _text(result.get("finding_id"))
    return [_finalize_goal_handoff(goal) for goal in goals.values()]


def _finalize_goal_handoff(goal: dict[str, Any]) -> dict[str, Any]:
    actionable = (
        int(goal.get("accept_count") or 0)
        + int(goal.get("reject_count") or 0)
        + int(goal.get("correct_count") or 0)
    )
    unresolved = (
        int(goal.get("unclear_count") or 0)
        + int(goal.get("skip_count") or 0)
        + int(goal.get("missing_count") or 0)
    )
    if actionable:
        next_action = "human confirm actionable recommendations"
    elif unresolved:
        next_action = "resolve unclear or missing agent recommendations"
    else:
        next_action = "no pending recommendations"
    return {
        **goal,
        "actionable_count": actionable,
        "unresolved_count": unresolved,
        "next_action": next_action,
    }


def _check_accept_recommendation(
    row: dict[str, Any],
    *,
    line_number: int,
    finding_id: str,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    gate = _mapping(row.get("acceptance_gate"))
    if not gate:
        errors.append(
            _issue(
                line_number,
                finding_id,
                "agent accept recommendation requires acceptance_gate",
            )
        )
        return
    if not bool(gate.get("accept_allowed")):
        errors.append(
            _issue(
                line_number,
                finding_id,
                "agent accept recommendation is blocked by acceptance_gate",
            )
        )
    blocking_missing = _strings(gate.get("blocking_missing"))
    if blocking_missing:
        errors.append(
            _issue(
                line_number,
                finding_id,
                "agent accept recommendation has blocking gaps: "
                + ", ".join(blocking_missing),
            )
        )
    review_checks = _strings(gate.get("review_checks"))
    if review_checks:
        warnings.append(
            _issue(
                line_number,
                finding_id,
                "human must verify acceptance checks: " + "; ".join(review_checks),
            )
        )


def _recommendation_counts(row_results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in row_results:
        recommendation = _text(result.get("recommendation")) or "missing"
        counts[recommendation] = counts.get(recommendation, 0) + 1
    return counts


def _is_agent_reviewer(value: str) -> bool:
    normalized = value.lower()
    return normalized.startswith("ai-reviewer") or normalized.startswith("agent-")


def _issue(line_number: int, finding_id: str, message: str) -> dict[str, Any]:
    return {
        "line": line_number,
        "finding_id": finding_id,
        "message": message,
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    return [_text(item) for item in value if _text(item)] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


if __name__ == "__main__":
    main()
