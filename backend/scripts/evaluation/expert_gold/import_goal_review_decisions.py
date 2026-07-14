#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
ACTION_VALUES = frozenset({"accept", "reject", "correct", "skip"})
REJECT_ISSUES = frozenset(
    {
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
    }
)


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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = import_review_decisions(
        input_path=Path(args.input_path),
        reviewer=args.reviewer,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "fail":
        raise SystemExit(1)


def import_review_decisions(
    *,
    input_path: Path,
    reviewer: str,
    dry_run: bool = False,
    feedback_service: Any | None = None,
) -> dict[str, Any]:
    reviewer = _human_reviewer(reviewer)
    rows = _read_jsonl(input_path)
    decisions = [_decision_from_row(row, line_number=index + 1) for index, row in enumerate(rows)]
    errors = [decision for decision in decisions if decision["status"] == "error"]
    valid_decisions = [decision for decision in decisions if decision["status"] == "ready"]
    if errors:
        return _summary(
            status="fail",
            dry_run=dry_run,
            total=len(rows),
            written=0,
            skipped=sum(1 for decision in decisions if decision.get("action") == "skip"),
            counts={},
            errors=errors,
            affected_goals=[],
        )
    if dry_run:
        return _summary(
            status="pass",
            dry_run=True,
            total=len(rows),
            written=0,
            skipped=sum(1 for decision in decisions if decision.get("action") == "skip"),
            counts=_counts(valid_decisions),
            errors=[],
            affected_goals=[],
        )

    service = feedback_service or _build_feedback_service()
    written = 0
    for decision in valid_decisions:
        action = decision["action"]
        if action == "skip":
            continue
        payload = decision["payload"]
        if action == "correct":
            service.record_curation(reviewer=reviewer, **payload)
        else:
            service.record_feedback(reviewer=reviewer, **payload)
        written += 1
    affected_goals = _affected_goal_summaries(service, valid_decisions)
    return _summary(
        status="pass",
        dry_run=False,
        total=len(rows),
        written=written,
        skipped=sum(1 for decision in decisions if decision.get("action") == "skip"),
        counts=_counts(valid_decisions),
        errors=[],
        affected_goals=affected_goals,
    )


def _build_feedback_service():
    backend_root = str(DEFAULT_BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from application.evaluation import ResearchUnderstandingFeedbackService  # noqa: PLC0415

    return ResearchUnderstandingFeedbackService()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _decision_from_row(row: dict[str, Any], *, line_number: int) -> dict[str, Any]:
    action = _text(row.get("action")).lower()
    if action not in ACTION_VALUES:
        return _error(line_number, action, "action must be accept, reject, correct, or skip")
    if action == "skip":
        return {"status": "ready", "line": line_number, "action": "skip", "payload": {}}

    required = ["collection_id", "goal_id", "finding_id"]
    missing = [field for field in required if not _text(row.get(field))]
    if missing:
        return _error(line_number, action, f"missing required field(s): {', '.join(missing)}")

    if action == "accept":
        return {
            "status": "ready",
            "line": line_number,
            "action": action,
            "payload": {
                "collection_id": _text(row.get("collection_id")),
                "scope_type": "goal",
                "scope_id": _text(row.get("goal_id")),
                "finding_id": _text(row.get("finding_id")),
                "claim_id": _optional_text(row.get("claim_id")),
                "review_status": "correct",
                "issue_type": "none",
                "note": _note(row, "Accepted from expert review JSONL."),
            },
        }
    if action == "reject":
        issue = _text(row.get("issue_type") or row.get("reject_issue")).lower()
        if issue not in REJECT_ISSUES:
            return _error(line_number, action, "reject requires a valid issue_type")
        return {
            "status": "ready",
            "line": line_number,
            "action": action,
            "payload": {
                "collection_id": _text(row.get("collection_id")),
                "scope_type": "goal",
                "scope_id": _text(row.get("goal_id")),
                "finding_id": _text(row.get("finding_id")),
                "claim_id": _optional_text(row.get("claim_id")),
                "review_status": "incorrect",
                "issue_type": issue,
                "note": _note(row, "Rejected from expert review JSONL."),
            },
        }
    return _correct_decision(row, line_number=line_number, action=action)


def _correct_decision(
    row: dict[str, Any],
    *,
    line_number: int,
    action: str,
) -> dict[str, Any]:
    target = _target(row)
    statement = _text(target.get("statement") or row.get("corrected_statement"))
    if not statement:
        return _error(line_number, action, "correct requires suggested_target.statement")
    evidence_ref_ids = _strings(
        target.get("evidence_ref_ids")
        or row.get("curated_evidence_ref_ids")
        or [item.get("evidence_ref_id") for item in _mapping_list(row.get("evidence"))]
    )
    if not evidence_ref_ids:
        return _error(line_number, action, "correct requires at least one evidence_ref_id")
    return {
        "status": "ready",
        "line": line_number,
        "action": action,
        "payload": {
            "collection_id": _text(row.get("collection_id")),
            "scope_type": "goal",
            "scope_id": _text(row.get("goal_id")),
            "finding_id": _text(row.get("finding_id")),
            "claim_id": _optional_text(row.get("claim_id")),
            "curated_claim_type": _text(target.get("claim_type") or row.get("claim_type"))
            or "finding",
            "curated_status": _text(target.get("status") or row.get("status")) or "limited",
            "curated_statement": statement,
            "curated_support_grade": _optional_text(
                target.get("support_grade") or row.get("support_grade")
            ),
            "curated_review_status": _text(target.get("review_status")) or "accepted",
            "curated_variables": _strings(target.get("variables") or row.get("variables")),
            "curated_mediators": _strings(target.get("mediators") or row.get("mediators")),
            "curated_outcomes": _strings(target.get("outcomes") or row.get("outcomes")),
            "curated_direction": _optional_text(target.get("direction") or row.get("direction")),
            "curated_scope_summary": _optional_text(
                target.get("scope_summary") or row.get("scope_summary")
            ),
            "curated_evidence_ref_ids": evidence_ref_ids,
            "curated_context_ids": _strings(
                target.get("context_ids") or row.get("curated_context_ids")
            ),
            "note": _note(row, "Corrected from expert review JSONL."),
        },
    }


def _human_reviewer(value: str) -> str:
    reviewer = _text(value)
    if not reviewer:
        raise ValueError("reviewer is required")
    normalized = reviewer.lower()
    if normalized.startswith("ai-reviewer") or normalized.startswith("agent-"):
        raise ValueError("reviewer must be a human expert id, not an AI/agent reviewer")
    return reviewer


def _target(row: dict[str, Any]) -> dict[str, Any]:
    target = row.get("suggested_target")
    return target if isinstance(target, dict) else {}


def _note(row: dict[str, Any], fallback: str) -> str:
    note = _text(row.get("expert_note") or row.get("note"))
    return note or fallback


def _counts(decisions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {action: 0 for action in sorted(ACTION_VALUES)}
    for decision in decisions:
        counts[decision["action"]] += 1
    return {key: value for key, value in counts.items() if value}


def _affected_goal_summaries(
    service: Any,
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    keys = sorted(
        {
            (
                _text(decision.get("payload", {}).get("collection_id")),
                _text(decision.get("payload", {}).get("scope_id")),
            )
            for decision in decisions
            if decision.get("action") != "skip"
        }
    )
    summaries = []
    for collection_id, goal_id in keys:
        if not collection_id or not goal_id:
            continue
        dataset = service.export_dataset(
            collection_id=collection_id,
            scope_type="goal",
            scope_id=goal_id,
        )
        summaries.append(_goal_readiness_summary(dataset))
    return summaries


def _goal_readiness_summary(dataset: dict[str, Any]) -> dict[str, Any]:
    quality = dataset.get("quality_summary")
    quality = quality if isinstance(quality, dict) else {}
    items = _mapping_list(dataset.get("items"))
    training_ready = [
        item for item in items if _text(item.get("dataset_use_status")) == "training_ready"
    ]
    return {
        "collection_id": _text(dataset.get("collection_id")),
        "goal_id": _text(dataset.get("scope_id")),
        "item_count": int(dataset.get("item_count") or len(items)),
        "training_ready_count": int(
            quality.get("training_ready_sample_count") or len(training_ready)
        ),
        "training_message_count": int(
            quality.get("training_message_sample_count")
            or sum(1 for item in training_ready if _has_training_messages(item))
        ),
        "protocol_ready_count": sum(
            1 for item in training_ready if _has_protocol_design_inputs(item)
        ),
        "review_candidate_count": int(
            quality.get("review_candidate_sample_count")
            or sum(
                1
                for item in items
                if _text(item.get("dataset_use_status")) == "review_candidate"
            )
        ),
        "rejected_count": int(
            quality.get("rejected_count")
            or sum(
                1
                for item in items
                if _text(item.get("dataset_use_status")) == "rejected"
            )
        ),
        "next_review_finding_id": _text(quality.get("next_review_finding_id")),
    }


def _has_training_messages(item: dict[str, Any]) -> bool:
    messages = _mapping_list(item.get("training_messages"))
    return len(messages) >= 2 and all(
        _text(message.get("role")) and _text(message.get("content"))
        for message in messages
    )


def _has_protocol_design_inputs(item: dict[str, Any]) -> bool:
    if not _has_training_messages(item):
        return False
    target = item.get("expert_target")
    target = target if isinstance(target, dict) else {}
    prediction = item.get("system_prediction")
    prediction = prediction if isinstance(prediction, dict) else {}
    statement = _text(target.get("statement") or prediction.get("statement"))
    variables = _strings(target.get("variables") or prediction.get("variables"))
    outcomes = _strings(target.get("outcomes") or prediction.get("outcomes"))
    direction = _text(target.get("direction") or prediction.get("direction"))
    scope = _text(target.get("scope_summary") or prediction.get("scope_summary"))
    evidence = _mapping_list(item.get("training_evidence_refs"))
    return bool(statement and variables and outcomes and (direction or scope) and evidence)


def _summary(
    *,
    status: str,
    dry_run: bool,
    total: int,
    written: int,
    skipped: int,
    counts: dict[str, int],
    errors: list[dict[str, Any]],
    affected_goals: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": status,
        "dry_run": dry_run,
        "total_rows": total,
        "written_count": written,
        "skipped_count": skipped,
        "counts": counts,
        "errors": errors,
        "affected_goals": affected_goals,
    }


def _error(line_number: int, action: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "line": line_number,
        "action": action,
        "message": message,
    }


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        text = _text(value)
        return [text] if text else []
    if isinstance(value, dict):
        return []
    try:
        return [text for item in value if (text := _text(item))]
    except TypeError:
        return []


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


if __name__ == "__main__":
    main()
