#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlencode
from urllib import request as request_url
from urllib.error import HTTPError, URLError


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COLLECTION_ID = "col_0cc5013fdb3c"
DEFAULT_GOAL_IDS = (
    "goal_0914003ad572",
    "goal_1a7a26d850b9",
    "goal_399171646354",
    "goal_061c9c049e69",
    "goal_6bf7d2c1030e",
    "goal_3037e425673a",
)
REVIEW_PACKET_QUOTE_LIMIT = 360
REVIEW_ACTION_OPTIONS = ("accept", "reject", "correct", "skip")
REVIEW_INSTRUCTIONS = (
    "Set action=accept only after the finding, direction, scope, and cited "
    "evidence match. Set action=reject with issue_type when the evidence does "
    "not support the finding. Set action=correct with suggested_target when "
    "the finding is partly right. Leave action=skip for unchecked rows."
)
REVIEW_RISK_FLAGS = {
    "accept_as_paper_level": "Paper-level evidence; do not treat as cross-paper conclusion without confirmation.",
    "review_table_rows": "Table-row finding; verify selected rows and changed variables before accepting.",
    "verify_table_rows": "Parsed table alignment is uncertain; verify source table before accepting.",
    "review_table_variables": "Multiple table variables may change together; avoid assigning a single-variable effect without checking.",
    "check_mechanism_requirement": "Mechanism evidence may be missing; decide whether the final label needs mechanism support.",
    "resolve_conflict": "Conflicting direction; resolve evidence conflict before downstream use.",
}
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
            "Check confirmed-goal research-understanding dataset samples for "
            "evaluation and fine-tuning readiness."
        )
    )
    parser.add_argument(
        "--collection-id",
        default=DEFAULT_COLLECTION_ID,
        help="Collection id to check.",
    )
    parser.add_argument(
        "--goal-id",
        action="append",
        dest="goal_ids",
        help="Goal id to check. May repeat. Defaults to the local 6-goal 316L set.",
    )
    parser.add_argument(
        "--api-base-url",
        help=(
            "Optional running Lens API or frontend origin to check, for example "
            "http://localhost:5173. When set, the script reads dataset payloads "
            "over HTTP instead of local application services. Set "
            "LENS_CHECK_EMAIL and LENS_CHECK_PASSWORD when login is required."
        ),
    )
    parser.add_argument(
        "--require-training-ready",
        action="store_true",
        help=(
            "Fail unless each checked goal has at least one training-ready "
            "sample. By default the script only requires reviewable active "
            "samples."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("json", "review-packet", "review-jsonl", "messages-jsonl"),
        default="json",
        help=(
            "Output format. JSON is stable for automation; review-packet is a "
            "human-readable queue of candidate findings, evidence, and links; "
            "review-jsonl emits one candidate per line; messages-jsonl emits "
            "fine-tuning-compatible rows for training-ready samples."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = check_goal_dataset_quality(
        collection_id=args.collection_id,
        goal_ids=tuple(args.goal_ids or DEFAULT_GOAL_IDS),
        api_base_url=args.api_base_url,
        require_training_ready=args.require_training_ready,
        include_review_packet=args.format in {"review-packet", "review-jsonl"},
        include_training_export=args.format == "messages-jsonl",
    )
    if args.format == "review-packet":
        print(render_review_packet_summary(summary))
    elif args.format == "review-jsonl":
        sys.stdout.write(render_review_jsonl_summary(summary))
    elif args.format == "messages-jsonl":
        sys.stdout.write(render_messages_jsonl_summary(summary))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "fail":
        raise SystemExit(1)


def check_goal_dataset_quality(
    *,
    collection_id: str,
    goal_ids: tuple[str, ...] = DEFAULT_GOAL_IDS,
    api_base_url: str | None = None,
    require_training_ready: bool = False,
    include_review_packet: bool = False,
    include_training_export: bool = False,
) -> dict[str, Any]:
    backend_root = str(DEFAULT_BACKEND_ROOT)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

    cookie = _api_login_cookie(api_base_url.rstrip("/")) if api_base_url else ""
    goal_summaries = []
    checks: list[dict[str, str]] = []
    for goal_id in goal_ids:
        dataset = (
            fetch_goal_dataset_from_api(
                api_base_url=api_base_url.rstrip("/"),
                collection_id=collection_id,
                goal_id=goal_id,
                cookie=cookie,
            )
            if api_base_url
            else _local_goal_dataset(collection_id, goal_id)
        )
        goal_summary = evaluate_goal_dataset_payload(
            dataset,
            require_training_ready=require_training_ready,
        )
        goal_summary["goal_id"] = goal_id
        if include_review_packet:
            goal_summary["review_packet"] = build_goal_review_packet(
                dataset,
                collection_id=collection_id,
            )
        if include_training_export:
            goal_summary["training_export"] = build_goal_training_message_export(
                dataset,
            )
        goal_summaries.append(goal_summary)
        checks.extend(goal_summary["checks"])

    return {
        "status": "fail"
        if any(check["status"] == "fail" for check in checks)
        else "pass",
        "collection_id": collection_id,
        "goal_count": len(goal_ids),
        "goals": goal_summaries,
        "checks": checks,
    }


def _local_goal_dataset(collection_id: str, goal_id: str) -> dict[str, Any]:
    with contextlib.redirect_stdout(io.StringIO()):
        from application.evaluation import ResearchUnderstandingFeedbackService  # noqa: PLC0415

        return ResearchUnderstandingFeedbackService().export_dataset(
            collection_id=collection_id,
            scope_type="goal",
            scope_id=goal_id,
        )


def fetch_goal_dataset_from_api(
    *,
    api_base_url: str,
    collection_id: str,
    goal_id: str,
    cookie: str,
) -> dict[str, Any]:
    return _api_json_request(
        api_base_url,
        (
            f"/api/v1/collections/{collection_id}/research-understanding/dataset"
            f"?scope_type=goal&scope_id={goal_id}"
        ),
        cookie=cookie,
    )


def _api_login_cookie(base_url: str) -> str:
    email = os.getenv("LENS_CHECK_EMAIL")
    password = os.getenv("LENS_CHECK_PASSWORD")
    if not email and not password:
        return ""
    if not email or not password:
        raise RuntimeError(
            "set both LENS_CHECK_EMAIL and LENS_CHECK_PASSWORD for API checks"
        )
    response = _api_json_request(
        base_url,
        "/api/v1/auth/login",
        method="POST",
        payload={"email": email, "password": password},
        include_headers=True,
    )
    headers = response["headers"]
    cookie = str(headers.get("Set-Cookie") or headers.get("set-cookie") or "")
    if not cookie:
        raise RuntimeError("POST /api/v1/auth/login did not return Set-Cookie")
    return cookie.split(";", 1)[0]


def _api_json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    cookie: str = "",
    include_headers: bool = False,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    request = request_url.Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with request_url.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
            if include_headers:
                return {"payload": data, "headers": response.headers}
            return data
    except HTTPError as exc:
        raise RuntimeError(
            f"{method} {path} failed: {exc.code} {exc.reason}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc


def evaluate_goal_dataset_payload(
    dataset: dict[str, Any],
    *,
    require_training_ready: bool = False,
) -> dict[str, Any]:
    goal_id = str(dataset.get("scope_id") or "")
    quality = _mapping(dataset.get("quality_summary"))
    warning_counts = _mapping(quality.get("warning_counts"))
    items = _mapping_list(dataset.get("items"))
    training_ready_items = [
        item for item in items if _text(item.get("dataset_use_status")) == "training_ready"
    ]
    training_message_ready_items = [
        item for item in training_ready_items if _has_fine_tuning_messages(item)
    ]
    protocol_ready_items = [
        item for item in training_message_ready_items if _has_protocol_design_inputs(item)
    ]
    active_items = [
        item
        for item in items
        if _text(item.get("dataset_use_status")) in {"training_ready", "review_candidate"}
    ]
    checks = [
        _check(
            goal_id,
            "dataset exports at least one sample",
            bool(items),
            f"items={len(items)}",
        ),
        _check(
            goal_id,
            "dataset has at least one active sample",
            bool(active_items),
            (
                f"training_ready={len(training_ready_items)}; "
                f"review_candidate={len(active_items) - len(training_ready_items)}"
            ),
        ),
        _check(
            goal_id,
            "dataset has no unavailable or failed traces",
            not warning_counts.get("unavailable_trace")
            and not warning_counts.get("failed_trace"),
            (
                f"unavailable_trace={warning_counts.get('unavailable_trace', 0)}; "
                f"failed_trace={warning_counts.get('failed_trace', 0)}"
            ),
        ),
        _check(
            goal_id,
            "active samples include text input blocks",
            all(_has_text_input_block(item) for item in active_items),
            _sample_failure_detail(
                item for item in active_items if not _has_text_input_block(item)
            ),
        ),
        _check(
            goal_id,
            "active samples include traceable training evidence",
            all(_has_traceable_training_evidence(item) for item in active_items),
            _sample_failure_detail(
                item
                for item in active_items
                if not _has_traceable_training_evidence(item)
            ),
        ),
        _check(
            goal_id,
            "training-ready samples include expert target",
            all(_mapping(item.get("expert_target")) for item in training_ready_items),
            _sample_failure_detail(
                item
                for item in training_ready_items
                if not _mapping(item.get("expert_target"))
            ),
        ),
        _check(
            goal_id,
            "training-ready samples include fine-tuning messages",
            all(_has_fine_tuning_messages(item) for item in training_ready_items),
            _sample_failure_detail(
                item
                for item in training_ready_items
                if not _has_fine_tuning_messages(item)
            ),
        ),
        _check(
            goal_id,
            "training-ready samples include protocol design inputs",
            all(_has_protocol_design_inputs(item) for item in training_ready_items),
            _sample_failure_detail(
                item
                for item in training_ready_items
                if not _has_protocol_design_inputs(item)
            ),
        ),
    ]
    if require_training_ready:
        checks.insert(
            2,
            _check(
                goal_id,
                "dataset has at least one training-ready sample",
                bool(training_ready_items),
                f"training_ready={len(training_ready_items)}",
            ),
        )
    return {
        "goal_id": goal_id,
        "item_count": len(items),
        "training_ready_count": len(training_ready_items),
        "training_message_ready_count": len(training_message_ready_items),
        "protocol_ready_count": len(protocol_ready_items),
        "review_candidate_count": len(
            [
                item
                for item in items
                if _text(item.get("dataset_use_status")) == "review_candidate"
            ]
        ),
        "next_review_finding_id": _next_review_finding_id(items),
        "next_review_action": _next_review_action(items),
        "by_error_category": dict(_mapping(quality.get("by_error_category"))),
        "by_review_reason": dict(_mapping(quality.get("by_review_reason"))),
        "by_system_warning": dict(_mapping(quality.get("by_system_warning"))),
        "by_review_candidate_reason": dict(
            _mapping(quality.get("by_review_candidate_reason"))
        ),
        "by_review_candidate_warning": dict(
            _mapping(quality.get("by_review_candidate_warning"))
        ),
        "by_trace_status": dict(_mapping(quality.get("by_trace_status"))),
        "warning_counts": dict(warning_counts),
        "checks": checks,
    }


def build_goal_review_packet(
    dataset: dict[str, Any],
    *,
    collection_id: str,
) -> dict[str, Any]:
    goal_id = _text(dataset.get("scope_id"))
    candidates = []
    for item in _mapping_list(dataset.get("items")):
        if _text(item.get("dataset_use_status")) != "review_candidate":
            continue
        finding_id = _text(item.get("finding_id"))
        prediction = _mapping(item.get("system_prediction"))
        expert_target = _mapping(item.get("expert_target"))
        evidence_records = (
            _mapping_list(item.get("training_evidence_refs"))
            or _mapping_list(item.get("evidence_refs"))
            or _mapping_list(item.get("input_blocks"))
        )
        review_reasons = _text_list(prediction.get("review_reasons"))
        warnings = _text_list(prediction.get("warnings"))
        review_action = _mapping(item.get("review_action"))
        candidates.append(
            {
                "sample_id": _text(item.get("sample_id")),
                "finding_id": finding_id,
                "open_url": _goal_review_url(
                    collection_id,
                    goal_id,
                    finding_id=finding_id,
                ),
                "presentation_bucket": _text(item.get("presentation_bucket")),
                "trace_status": _text(item.get("trace_status")),
                "statement": _text(prediction.get("statement"))
                or _text(expert_target.get("statement")),
                "variables": _text_list(prediction.get("variables")),
                "mediators": _text_list(prediction.get("mediators")),
                "outcomes": _text_list(prediction.get("outcomes")),
                "direction": _text(prediction.get("direction")),
                "scope_summary": _text(prediction.get("scope_summary")),
                "support_grade": _text(prediction.get("support_grade")),
                "review_status": _text(prediction.get("review_status"))
                or _text(expert_target.get("review_status")),
                "review_reasons": review_reasons,
                "warnings": warnings,
                "recommended_action": _text(review_action.get("label"))
                or _review_packet_action(
                    review_reasons=review_reasons,
                    warnings=warnings,
                    evidence_records=evidence_records,
                ),
                "recommended_action_code": _text(review_action.get("code")),
                "suggested_target": {
                    "source": _text(expert_target.get("source")),
                    "review_status": _text(expert_target.get("review_status")),
                    "issue_type": _text(expert_target.get("issue_type")),
                    "statement": _text(expert_target.get("statement")),
                    "note": _text(expert_target.get("note")),
                    "reviewer": _text(expert_target.get("reviewer")),
                }
                if expert_target
                else {},
                "evidence": [
                    _review_evidence_record(record) for record in evidence_records
                ],
            }
        )
    return {
        "goal_id": goal_id,
        "review_url": _goal_review_url(collection_id, goal_id),
        "candidate_count": len(candidates),
        "risk_summary": _review_risk_summary(candidates),
        "candidates": candidates,
    }


def build_goal_training_message_export(dataset: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for item in _mapping_list(dataset.get("items")):
        if _text(item.get("dataset_use_status")) != "training_ready":
            continue
        if not _has_fine_tuning_messages(item):
            continue
        rows.append(
            {
                "messages": [
                    {
                        "role": _text(message.get("role")),
                        "content": _text(message.get("content")),
                    }
                    for message in _mapping_list(item.get("training_messages"))
                    if _text(message.get("role")) and _text(message.get("content"))
                ]
            }
        )
    return {
        "goal_id": _text(dataset.get("scope_id")),
        "row_count": len(rows),
        "rows": rows,
    }


def _review_risk_summary(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        action_code = _text(candidate.get("recommended_action_code"))
        if action_code:
            key = f"action:{action_code}"
            counts[key] = counts.get(key, 0) + 1
        for reason in _text_list(candidate.get("review_reasons")):
            key = f"reason:{reason}"
            counts[key] = counts.get(key, 0) + 1
        for warning in _text_list(candidate.get("warnings")):
            key = f"warning:{warning}"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def render_review_packet_summary(summary: dict[str, Any]) -> str:
    lines = [
        f"Lens review packet: {summary.get('status')}",
        f"Collection: {summary.get('collection_id')}",
        "",
        "Action rule: accept if the finding, direction, condition, and evidence match; "
        "correct if the finding is partially right; reject if the evidence does not "
        "support it.",
    ]
    goals = _mapping_list(summary.get("goals"))
    for goal in goals:
        packet = _mapping(goal.get("review_packet"))
        candidates = _mapping_list(packet.get("candidates"))
        if not candidates:
            continue
        lines.extend(
            [
                "",
                f"Goal {packet.get('goal_id')}: {len(candidates)} review candidate(s)",
                f"Open: {packet.get('review_url')}",
            ]
        )
        risk_summary = _mapping(packet.get("risk_summary"))
        if risk_summary:
            lines.append(f"Risk summary: {_risk_summary_text(risk_summary)}")
        for index, candidate in enumerate(candidates, start=1):
            lines.extend(
                [
                    "",
                    f"  {index}. {_clip(candidate.get('statement'), 240)}",
                    (
                        "     fields: "
                        f"variables={_join(candidate.get('variables'))}; "
                        f"outcomes={_join(candidate.get('outcomes'))}; "
                        f"direction={_text(candidate.get('direction')) or 'n/a'}"
                    ),
                    (
                        "     status: "
                        f"bucket={_text(candidate.get('presentation_bucket')) or 'n/a'}; "
                        f"support={_text(candidate.get('support_grade')) or 'n/a'}; "
                        f"review={_text(candidate.get('review_status')) or 'n/a'}; "
                        f"trace={_text(candidate.get('trace_status')) or 'n/a'}"
                    ),
                    f"     open finding: {_text(candidate.get('open_url')) or packet.get('review_url')}",
                    f"     recommended action: {_text(candidate.get('recommended_action'))}",
                ]
            )
            review_reasons = _text_list(candidate.get("review_reasons"))
            warnings = _text_list(candidate.get("warnings"))
            if review_reasons:
                lines.append(f"     review reasons: {_join(review_reasons)}")
            if warnings:
                lines.append(f"     warnings: {_join(warnings)}")
            if _text(candidate.get("scope_summary")):
                lines.append(f"     scope: {_clip(candidate.get('scope_summary'), 220)}")
            suggested = _mapping(candidate.get("suggested_target"))
            if suggested:
                lines.append(
                    "     suggested target: "
                    f"{_clip(suggested.get('statement'), 260)}"
                )
                if _text(suggested.get("note")):
                    lines.append(f"     suggestion note: {_clip(suggested.get('note'), 260)}")
            evidence = _mapping_list(candidate.get("evidence"))
            if evidence:
                lines.append("     evidence:")
                for evidence_index, record in enumerate(evidence, start=1):
                    label = _text(record.get("label")) or _text(record.get("source_ref"))
                    page = _text(record.get("page"))
                    page_text = (
                        f" / p. {page}"
                        if page and f"p. {page}" not in label
                        else ""
                    )
                    lines.extend(
                        [
                            f"       {evidence_index}. {label}{page_text}",
                            f"          quote: {_clip(record.get('quote'))}",
                            f"          open: {_text(record.get('href')) or 'n/a'}",
                        ]
                    )
    if len(lines) == 4:
        lines.append("")
        lines.append("No review candidates found.")
    return "\n".join(lines)


def _risk_summary_text(risk_summary: dict[str, Any]) -> str:
    return ", ".join(
        f"{key}={value}" for key, value in sorted(risk_summary.items())
    )


def render_review_jsonl_summary(summary: dict[str, Any]) -> str:
    rows = []
    collection_id = _text(summary.get("collection_id"))
    for goal in _mapping_list(summary.get("goals")):
        packet = _mapping(goal.get("review_packet"))
        goal_id = _text(packet.get("goal_id")) or _text(goal.get("goal_id"))
        for candidate in _mapping_list(packet.get("candidates")):
            rows.append(
                {
                    "collection_id": collection_id,
                    "goal_id": goal_id,
                    "sample_id": _text(candidate.get("sample_id")),
                    "finding_id": _text(candidate.get("finding_id")),
                    "open_url": _text(candidate.get("open_url"))
                    or _text(packet.get("review_url")),
                    "statement": _text(candidate.get("statement")),
                    "variables": _text_list(candidate.get("variables")),
                    "mediators": _text_list(candidate.get("mediators")),
                    "outcomes": _text_list(candidate.get("outcomes")),
                    "direction": _text(candidate.get("direction")),
                    "scope_summary": _text(candidate.get("scope_summary")),
                    "support_grade": _text(candidate.get("support_grade")),
                    "review_status": _text(candidate.get("review_status")),
                    "presentation_bucket": _text(candidate.get("presentation_bucket")),
                    "trace_status": _text(candidate.get("trace_status")),
                    "review_reasons": _text_list(candidate.get("review_reasons")),
                    "warnings": _text_list(candidate.get("warnings")),
                    "recommended_action": _text(candidate.get("recommended_action")),
                    "recommended_action_code": _text(
                        candidate.get("recommended_action_code")
                    ),
                    "review_instructions": REVIEW_INSTRUCTIONS,
                    "review_risk_flags": _review_risk_flags(
                        _text(candidate.get("recommended_action_code")),
                        _text_list(candidate.get("review_reasons")),
                        _text_list(candidate.get("warnings")),
                    ),
                    "action": "skip",
                    "allowed_actions": list(REVIEW_ACTION_OPTIONS),
                    "issue_type": "",
                    "reject_issue_options": list(REJECT_ISSUE_OPTIONS),
                    "expert_note": "",
                    "suggested_target": dict(
                        _mapping(candidate.get("suggested_target"))
                    ),
                    "evidence": _mapping_list(candidate.get("evidence")),
                }
            )
    return _jsonl(rows)


def _review_risk_flags(
    recommended_action_code: str,
    review_reasons: list[str],
    warnings: list[str],
) -> list[str]:
    flags = []
    if recommended_action_code in REVIEW_RISK_FLAGS:
        flags.append(REVIEW_RISK_FLAGS[recommended_action_code])
    for value in [*review_reasons, *warnings]:
        if value in REVIEW_RISK_FLAGS and REVIEW_RISK_FLAGS[value] not in flags:
            flags.append(REVIEW_RISK_FLAGS[value])
    return flags


def render_messages_jsonl_summary(summary: dict[str, Any]) -> str:
    rows = []
    for goal in _mapping_list(summary.get("goals")):
        export = _mapping(goal.get("training_export"))
        rows.extend(_mapping_list(export.get("rows")))
    return _jsonl(rows)


def _has_text_input_block(item: dict[str, Any]) -> bool:
    return any(_text(block.get("text")) for block in _mapping_list(item.get("input_blocks")))


def _has_traceable_training_evidence(item: dict[str, Any]) -> bool:
    refs = _mapping_list(item.get("training_evidence_refs"))
    return bool(refs) and all(
        _text(ref.get("source_ref"))
        and _text(ref.get("href"))
        and (_text(ref.get("quote")) or _text(ref.get("source_text")))
        for ref in refs
    )


def _has_fine_tuning_messages(item: dict[str, Any]) -> bool:
    expert_target = _mapping(item.get("expert_target"))
    target_statement = _text(expert_target.get("statement"))
    if not target_statement:
        return False
    messages = _mapping_list(item.get("training_messages"))
    if len(messages) < 2:
        return False
    if _text(messages[0].get("role")) != "user" or not _text(
        messages[0].get("content")
    ):
        return False
    if _text(messages[-1].get("role")) != "assistant":
        return False
    assistant_content = _text(messages[-1].get("content"))
    if not assistant_content:
        return False
    try:
        assistant_payload = json.loads(assistant_content)
    except json.JSONDecodeError:
        return False
    if not isinstance(assistant_payload, dict):
        return False
    return _normalized_text(assistant_payload.get("statement")) == _normalized_text(
        target_statement
    )


def _has_protocol_design_inputs(item: dict[str, Any]) -> bool:
    if not _has_fine_tuning_messages(item):
        return False
    target = _mapping(item.get("expert_target"))
    prediction = _mapping(item.get("system_prediction"))
    statement = _text(target.get("statement") or prediction.get("statement"))
    variables = _text_list(target.get("variables")) or _text_list(
        prediction.get("variables")
    )
    outcomes = _text_list(target.get("outcomes")) or _text_list(
        prediction.get("outcomes")
    )
    direction = _text(target.get("direction") or prediction.get("direction"))
    scope = _text(target.get("scope_summary") or prediction.get("scope_summary"))
    return (
        bool(statement)
        and bool(variables)
        and bool(outcomes)
        and bool(direction or scope)
        and _has_traceable_training_evidence(item)
    )


def _next_review_finding_id(items: list[dict[str, Any]]) -> str:
    for item in items:
        if _text(item.get("dataset_use_status")) == "review_candidate":
            return _text(item.get("finding_id"))
    return ""


def _next_review_action(items: list[dict[str, Any]]) -> dict[str, str]:
    for item in items:
        if _text(item.get("dataset_use_status")) != "review_candidate":
            continue
        review_action = _mapping(item.get("review_action"))
        code = _text(review_action.get("code"))
        label = _text(review_action.get("label"))
        if code or label:
            return {"code": code, "label": label}
        prediction = _mapping(item.get("system_prediction"))
        evidence_records = (
            _mapping_list(item.get("training_evidence_refs"))
            or _mapping_list(item.get("evidence_refs"))
            or _mapping_list(item.get("input_blocks"))
        )
        return {
            "code": "",
            "label": _review_packet_action(
                review_reasons=_text_list(prediction.get("review_reasons")),
                warnings=_text_list(prediction.get("warnings")),
                evidence_records=evidence_records,
            ),
        }
    return {}


def _sample_failure_detail(items: Any) -> str:
    failures = [
        _text(item.get("sample_id")) or _text(item.get("finding_id")) or "unknown"
        for item in items
    ]
    if not failures:
        return "none"
    return "samples=" + json.dumps(failures[:10], ensure_ascii=False)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _review_evidence_record(record: dict[str, Any]) -> dict[str, str]:
    return {
        "evidence_ref_id": _text(record.get("evidence_ref_id")),
        "label": _text(record.get("label"))
        or _text(record.get("source_label"))
        or _text(record.get("source_kind")),
        "source_ref": _text(record.get("source_ref")),
        "page": _text(record.get("page")),
        "href": _text(record.get("href")),
        "quote": _text(record.get("quote"))
        or _text(record.get("source_text"))
        or _text(record.get("training_source_text"))
        or _text(record.get("text")),
    }


def _review_packet_action(
    *,
    review_reasons: list[str],
    warnings: list[str],
    evidence_records: list[dict[str, Any]],
) -> str:
    risk_codes = {*review_reasons, *warnings}
    if "table_row_alignment_uncertain" in risk_codes:
        return "verify parsed table rows before accepting or correcting"
    if "non_single_variable_table_comparison" in risk_codes:
        return "check whether multiple table variables changed before accepting"
    if "table_row_needs_expert_review" in risk_codes:
        return "review selected table rows before accepting or correcting"
    if "conflicting_direction" in risk_codes:
        return "resolve conflicting evidence before downstream use"
    if "missing_direct_result_evidence" in risk_codes or not evidence_records:
        return "repair or reject the evidence binding"
    if "missing_mechanism_evidence" in risk_codes:
        return "check whether mechanism evidence is required for the final label"
    if "needs_cross_paper_confirmation" in risk_codes or "single_paper_evidence" in risk_codes:
        return "accept only as paper-level evidence unless another paper confirms it"
    return "accept, reject, or correct after checking the evidence"


def _text_list(value: Any) -> list[str]:
    return [_text(item) for item in value if _text(item)] if isinstance(value, list) else []


def _join(value: Any) -> str:
    items = value if isinstance(value, list) else []
    text = ", ".join(_text(item) for item in items if _text(item))
    return text or "n/a"


def _clip(value: Any, limit: int = REVIEW_PACKET_QUOTE_LIMIT) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _goal_review_url(
    collection_id: str,
    goal_id: str,
    *,
    finding_id: str = "",
) -> str:
    params = {"review": "queue"}
    if finding_id:
        params["finding_id"] = finding_id
    return f"/collections/{collection_id}/goals/{goal_id}?{urlencode(params)}"


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalized_text(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _jsonl(rows: list[dict[str, Any]]) -> str:
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    return f"{body}\n" if body else ""


def _check(goal_id: str, name: str, passed: bool, detail: str) -> dict[str, str]:
    return {
        "status": "pass" if passed else "fail",
        "goal_id": goal_id,
        "name": name,
        "detail": detail,
    }


if __name__ == "__main__":
    main()
