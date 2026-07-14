from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from application.evaluation.research_understanding_feedback_service import (
    ResearchUnderstandingFeedbackService,
)


ACTION_VALUES = frozenset({"accept", "reject", "correct", "skip"})
AGENT_RECOMMENDATION_VALUES = frozenset(
    {"accept", "reject", "correct", "skip", "unclear"}
)
RISKY_ACCEPT_ACTION_CODES = frozenset(
    {
        "accept_as_paper_level",
        "review_table_rows",
        "verify_table_rows",
        "review_table_variables",
        "check_mechanism_evidence",
        "check_mechanism_requirement",
        "resolve_conflict",
    }
)
RISKY_ACCEPT_REASONS = frozenset(
    {
        "needs_cross_paper_confirmation",
        "missing_mechanism_evidence",
        "table_row_needs_expert_review",
        "table_row_alignment_uncertain",
        "non_single_variable_table_comparison",
    }
)
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


class ResearchUnderstandingReviewImportService:
    def __init__(
        self,
        feedback_service: ResearchUnderstandingFeedbackService | Any | None = None,
    ) -> None:
        self.feedback_service = feedback_service or ResearchUnderstandingFeedbackService()

    def import_rows(
        self,
        *,
        rows: list[dict[str, Any]],
        reviewer: str,
        dry_run: bool = False,
        fail_on_warnings: bool = False,
    ) -> dict[str, Any]:
        reviewer = _human_reviewer(reviewer)
        decisions = [
            _decision_from_row(
                _confirmed_agent_review_row(row, line_number=index + 1),
                line_number=index + 1,
            )
            for index, row in enumerate(rows)
        ]
        errors = [decision for decision in decisions if decision["status"] == "error"]
        valid_decisions = [
            decision for decision in decisions if decision["status"] == "ready"
        ]
        review_progress = _review_progress(valid_decisions)
        if not errors:
            errors.extend(
                _dataset_validation_errors(self.feedback_service, valid_decisions)
            )
        if errors:
            return _summary(
                status="fail",
                dry_run=dry_run,
                total=len(rows),
                written=0,
                skipped=sum(
                    1 for decision in decisions if decision.get("action") == "skip"
                ),
                counts={},
                errors=errors,
                warnings=[],
                review_progress=review_progress,
                affected_goals=[],
            )
        warnings = _review_warnings(valid_decisions)
        warnings.extend(_actionable_decision_warnings(valid_decisions))
        if fail_on_warnings and warnings:
            return _summary(
                status="fail",
                dry_run=dry_run,
                total=len(rows),
                written=0,
                skipped=sum(
                    1 for decision in decisions if decision.get("action") == "skip"
                ),
                counts=_counts(valid_decisions),
                errors=[
                    _error(
                        int(warning["line"]),
                        _text(warning["action"]),
                        f"review warning requires resolution: {warning['message']}",
                    )
                    for warning in warnings
                ],
                warnings=warnings,
                review_progress=review_progress,
                affected_goals=[],
            )
        if dry_run:
            return _summary(
                status="pass",
                dry_run=True,
                total=len(rows),
                written=0,
                skipped=sum(
                    1 for decision in decisions if decision.get("action") == "skip"
                ),
                counts=_counts(valid_decisions),
                errors=[],
                warnings=warnings,
                review_progress=review_progress,
                affected_goals=[],
            )

        written = 0
        for decision in valid_decisions:
            action = decision["action"]
            if action == "skip":
                continue
            payload = decision["payload"]
            if action == "correct":
                self.feedback_service.record_curation(reviewer=reviewer, **payload)
            else:
                self.feedback_service.record_feedback(reviewer=reviewer, **payload)
            written += 1
        affected_goals = _affected_goal_summaries(
            self.feedback_service,
            valid_decisions,
        )
        return _summary(
            status="pass",
            dry_run=False,
            total=len(rows),
            written=written,
            skipped=sum(1 for decision in decisions if decision.get("action") == "skip"),
            counts=_counts(valid_decisions),
            errors=[],
            warnings=warnings,
            review_progress=review_progress,
            affected_goals=affected_goals,
        )

    def import_jsonl_file(
        self,
        *,
        input_path: Path,
        reviewer: str,
        dry_run: bool = False,
        fail_on_warnings: bool = False,
    ) -> dict[str, Any]:
        return self.import_rows(
            rows=read_review_jsonl(input_path),
            reviewer=reviewer,
            dry_run=dry_run,
            fail_on_warnings=fail_on_warnings,
        )


def read_review_jsonl(path: Path) -> list[dict[str, Any]]:
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
    if action == "__agent_review_error__":
        return _error(
            line_number,
            "skip",
            _text(row.get("agent_review_error")) or "invalid confirmed agent review",
        )
    if action not in ACTION_VALUES:
        return _error(line_number, action, "action must be accept, reject, correct, or skip")
    if action == "skip":
        return {"status": "ready", "line": line_number, "action": "skip", "payload": {}}

    required = ["collection_id", "goal_id", "finding_id"]
    missing = [field for field in required if not _text(row.get(field))]
    if missing:
        return _error(line_number, action, f"missing required field(s): {', '.join(missing)}")

    if action == "accept":
        blocking_missing = _protocol_blocking_missing(row)
        if blocking_missing:
            return _error(
                line_number,
                action,
                (
                    "accept requires protocol_readiness without blocking gaps; "
                    f"use correct or reject for: {', '.join(blocking_missing)}"
                ),
            )
        return {
            "status": "ready",
            "line": line_number,
            "action": action,
            "review_warning": _review_warning(row),
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
            "review_warning": "",
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


def confirm_agent_review_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _confirmed_agent_review_row(row, line_number=index + 1)
        for index, row in enumerate(rows)
    ]


def _confirmed_agent_review_row(
    row: dict[str, Any],
    *,
    line_number: int,
) -> dict[str, Any]:
    if "agent_review" not in row:
        return row
    review = _mapping(row.get("agent_review"))
    output = dict(row)
    output["action"] = "skip"
    if not bool(review.get("human_confirmed")):
        return output
    recommendation = _text(review.get("recommendation")).lower()
    if recommendation not in AGENT_RECOMMENDATION_VALUES:
        return _agent_review_error_row(
            output,
            f"line {line_number}: agent_review.recommendation is not supported",
        )
    if recommendation in {"skip", "unclear"}:
        return output
    if recommendation == "accept":
        blocking_error = _confirmed_accept_error(output)
        if blocking_error:
            return _agent_review_error_row(output, f"line {line_number}: {blocking_error}")
        output["action"] = "accept"
        output["expert_note"] = _confirmed_note(output, review)
        return output
    if recommendation == "reject":
        issue_type = _text(review.get("issue_type")).lower()
        if not issue_type:
            return _agent_review_error_row(
                output,
                f"line {line_number}: confirmed reject requires issue_type",
            )
        output["action"] = "reject"
        output["issue_type"] = issue_type
        output["expert_note"] = _confirmed_note(output, review)
        return output
    target = _mapping(review.get("suggested_target"))
    if not _text(target.get("statement")):
        return _agent_review_error_row(
            output,
            f"line {line_number}: confirmed correct requires suggested_target.statement",
        )
    evidence_ref_ids = _strings(target.get("evidence_ref_ids"))
    if not evidence_ref_ids:
        return _agent_review_error_row(
            output,
            f"line {line_number}: confirmed correct requires evidence_ref_ids",
        )
    output["action"] = "correct"
    output["suggested_target"] = target
    output["curated_evidence_ref_ids"] = evidence_ref_ids
    output["expert_note"] = _confirmed_note(output, review)
    return output


def _confirmed_accept_error(row: dict[str, Any]) -> str:
    gate = _mapping(row.get("acceptance_gate"))
    blocking = _strings(gate.get("blocking_missing")) or _strings(
        row.get("protocol_blocking_missing")
    )
    if gate and (not bool(gate.get("accept_allowed")) or blocking):
        return "confirmed accept is blocked by acceptance_gate"
    if blocking:
        return "confirmed accept is blocked by acceptance_gate"
    return ""


def _agent_review_error_row(row: dict[str, Any], message: str) -> dict[str, Any]:
    output = dict(row)
    output["action"] = "__agent_review_error__"
    output["agent_review_error"] = message
    return output


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
        "review_warning": _review_warning(row),
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


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _confirmed_note(row: dict[str, Any], review: dict[str, Any]) -> str:
    note = _text(review.get("note"))
    existing = _text(row.get("expert_note"))
    return existing or note or "Human confirmed agent review suggestion."


def _note(row: dict[str, Any], fallback: str) -> str:
    note = _text(row.get("expert_note") or row.get("note"))
    return note or fallback


def _review_warning(row: dict[str, Any]) -> str:
    code = _text(row.get("recommended_action_code"))
    reasons = set(_strings(row.get("review_reasons")))
    risky_reasons = sorted(reasons & RISKY_ACCEPT_REASONS)
    if code in RISKY_ACCEPT_ACTION_CODES and risky_reasons:
        return (
            f"recommended_action_code={code}; review_reasons="
            f"{', '.join(risky_reasons)}"
        )
    if code in RISKY_ACCEPT_ACTION_CODES:
        return f"recommended_action_code={code}"
    if risky_reasons:
        return f"review_reasons={', '.join(risky_reasons)}"
    return ""


def _protocol_blocking_missing(row: dict[str, Any]) -> list[str]:
    acceptance_gate = row.get("acceptance_gate")
    if isinstance(acceptance_gate, dict):
        blocking = _strings(acceptance_gate.get("blocking_missing"))
        if blocking:
            return blocking
    readiness = row.get("protocol_readiness")
    if not isinstance(readiness, dict):
        return _strings(row.get("protocol_blocking_missing"))
    return _strings(readiness.get("blocking_missing"))


def _review_warnings(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "line": int(decision.get("line") or 0),
            "action": decision["action"],
            "finding_id": _text(decision.get("payload", {}).get("finding_id")),
            "message": decision["review_warning"],
        }
        for decision in decisions
        if decision.get("action") in {"accept", "correct"}
        and _text(decision.get("review_warning"))
    ]


def _actionable_decision_warnings(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(decision.get("action") in {"accept", "reject", "correct"} for decision in decisions):
        return []
    return [
        {
            "line": 0,
            "action": "skip",
            "finding_id": "",
            "message": (
                "no_actionable_decisions: all rows are skip; no expert labels "
                "will be written"
            ),
        }
    ]


def _counts(decisions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {action: 0 for action in sorted(ACTION_VALUES)}
    for decision in decisions:
        counts[decision["action"]] += 1
    return {key: value for key, value in counts.items() if value}


def _review_progress(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _counts(decisions)
    actionable_count = sum(
        counts.get(action, 0) for action in ("accept", "reject", "correct")
    )
    skipped_count = counts.get("skip", 0)
    next_steps = []
    if actionable_count == 0:
        next_steps.append(
            "change at least one reviewed row from skip to accept, reject, or correct"
        )
    if skipped_count:
        next_steps.append("leave unchecked rows as skip or review them later")
    if counts.get("accept", 0):
        next_steps.append("rerun dry-run with --fail-on-warnings before import")
    return {
        "actionable_count": actionable_count,
        "skipped_count": skipped_count,
        "needs_review_count": skipped_count,
        "ready_to_write": actionable_count > 0,
        "next_steps": next_steps,
    }


def _dataset_validation_errors(
    service: Any,
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    datasets = _datasets_for_decisions(service, decisions)
    errors: list[dict[str, Any]] = []
    for decision in decisions:
        action = decision.get("action")
        if action == "skip":
            continue
        payload = decision.get("payload", {})
        collection_id = _text(payload.get("collection_id"))
        goal_id = _text(payload.get("scope_id"))
        finding_id = _text(payload.get("finding_id"))
        dataset = datasets.get((collection_id, goal_id), {})
        item = _dataset_item(dataset, finding_id)
        if not item:
            errors.append(
                _error(
                    int(decision.get("line") or 0),
                    _text(action),
                    "finding_id does not exist in current goal dataset",
                )
            )
            continue
        claim_id = _text(payload.get("claim_id"))
        if claim_id and _text(item.get("claim_id")) != claim_id:
            errors.append(
                _error(
                    int(decision.get("line") or 0),
                    _text(action),
                    "claim_id does not match current goal dataset finding",
                )
            )
            continue
        if action == "correct":
            missing_refs = sorted(
                set(_strings(payload.get("curated_evidence_ref_ids")))
                - _dataset_evidence_ref_ids(item)
            )
            if missing_refs:
                errors.append(
                    _error(
                        int(decision.get("line") or 0),
                        _text(action),
                        (
                            "correct references evidence_ref_id(s) not present "
                            f"on current finding: {', '.join(missing_refs)}"
                        ),
                    )
                )
    return errors


def _datasets_for_decisions(
    service: Any,
    decisions: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    datasets = {}
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
    for collection_id, goal_id in keys:
        if not collection_id or not goal_id:
            continue
        datasets[(collection_id, goal_id)] = service.export_dataset(
            collection_id=collection_id,
            scope_type="goal",
            scope_id=goal_id,
        )
    return datasets


def _dataset_item(dataset: dict[str, Any], finding_id: str) -> dict[str, Any]:
    for item in _mapping_list(dataset.get("items")):
        if _text(item.get("finding_id")) == finding_id:
            return item
    return {}


def _dataset_evidence_ref_ids(item: dict[str, Any]) -> set[str]:
    records = (
        _mapping_list(item.get("training_evidence_refs"))
        or _mapping_list(item.get("evidence_refs"))
        or _mapping_list(item.get("input_blocks"))
    )
    return {
        ref_id
        for record in records
        if (ref_id := _text(record.get("evidence_ref_id")))
    }


def _affected_goal_summaries(
    service: Any,
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    datasets = _datasets_for_decisions(service, decisions)
    summaries = []
    for dataset in datasets.values():
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
        "readiness_issues": _readiness_issues(training_ready),
    }


def _has_training_messages(item: dict[str, Any]) -> bool:
    messages = _mapping_list(item.get("training_messages"))
    return len(messages) >= 2 and all(
        _text(message.get("role")) and _text(message.get("content"))
        for message in messages
    )


def _readiness_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    for item in items:
        missing_training = _training_message_missing(item)
        missing_protocol = _protocol_missing(item)
        if not missing_training and not missing_protocol:
            continue
        issues.append(
            {
                "finding_id": _text(item.get("finding_id")),
                "claim_id": _optional_text(item.get("claim_id")),
                "missing_training_message": missing_training,
                "missing_protocol_input": missing_protocol,
            }
        )
    return issues[:10]


def _training_message_missing(item: dict[str, Any]) -> list[str]:
    messages = _mapping_list(item.get("training_messages"))
    if len(messages) < 2:
        return ["message_pair"]
    missing = []
    if not any(
        _text(message.get("role")) == "user" and _text(message.get("content"))
        for message in messages
    ):
        missing.append("user_message")
    if not any(
        _text(message.get("role")) == "assistant" and _text(message.get("content"))
        for message in messages
    ):
        missing.append("assistant_message")
    return missing


def _protocol_missing(item: dict[str, Any]) -> list[str]:
    target = item.get("expert_target")
    target = target if isinstance(target, dict) else {}
    prediction = item.get("system_prediction")
    prediction = prediction if isinstance(prediction, dict) else {}
    missing = []
    if not _has_training_messages(item):
        missing.append("training_messages")
    if not _text(target.get("statement") or prediction.get("statement")):
        missing.append("statement")
    if not _strings(target.get("variables") or prediction.get("variables")):
        missing.append("variables")
    if not _strings(target.get("outcomes") or prediction.get("outcomes")):
        missing.append("outcomes")
    if not _text(target.get("direction") or prediction.get("direction")) and not _text(
        target.get("scope_summary") or prediction.get("scope_summary")
    ):
        missing.append("direction_or_scope")
    if not _mapping_list(item.get("training_evidence_refs")):
        missing.append("training_evidence_refs")
    return missing


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
    warnings: list[dict[str, Any]],
    review_progress: dict[str, Any],
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
        "warnings": warnings,
        "review_progress": review_progress,
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
