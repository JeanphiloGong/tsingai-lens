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
from urllib.parse import parse_qsl, urlsplit, urlunsplit
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
TABLE_ROW_REVIEW_PROMPT = (
    "Expert review is required before treating this as a material effect."
)
EXPERT_NOTE_PROMPTS = {
    "accept_as_paper_level": "Required: explain that the label is accepted only as paper-level evidence.",
    "review_table_rows": "Required: explain which table rows, variable column, and outcome values were checked.",
    "verify_table_rows": "Required: explain how parsed table-row alignment was verified.",
    "review_table_variables": "Required: explain why the selected variable can be interpreted despite other table variables.",
    "check_mechanism_requirement": "Required: explain whether mechanism evidence is required for this label.",
    "resolve_conflict": "Required: explain how the conflicting evidence was resolved.",
}
ACCEPTANCE_REVIEW_CHECKS = {
    "accept_as_paper_level": "Confirm the finding is only paper-level unless cross-paper evidence is present.",
    "needs_cross_paper_confirmation": "Confirm the finding is only paper-level unless cross-paper evidence is present.",
    "single_paper_evidence": "Confirm the finding is only paper-level unless cross-paper evidence is present.",
    "review_table_rows": "Verify the selected table rows, variable columns, and outcome values.",
    "table_row_needs_expert_review": "Verify the selected table rows, variable columns, and outcome values.",
    "verify_table_rows": "Verify parsed table-row alignment against the source table.",
    "table_row_alignment_uncertain": "Verify parsed table-row alignment against the source table.",
    "review_table_variables": "Check whether multiple table variables changed before assigning a single-variable effect.",
    "non_single_variable_table_comparison": "Check whether multiple table variables changed before assigning a single-variable effect.",
    "check_mechanism_requirement": "Decide whether mechanism evidence is required for this reviewed finding.",
    "missing_mechanism_evidence": "Decide whether mechanism evidence is required for this reviewed finding.",
    "resolve_conflict": "Resolve conflicting evidence direction before downstream use.",
    "conflicting_direction": "Resolve conflicting evidence direction before downstream use.",
    "repair_evidence_binding": "Repair or reject the evidence binding before accepting.",
    "missing_direct_result_evidence": "Repair or reject the evidence binding before accepting.",
    "validate_model_evidence": "Validate the model-prediction or validation evidence before accepting.",
    "model_validation_finding": "Validate the model-prediction or validation evidence before accepting.",
}
ACCEPT_BLOCKING_REVIEW_CODES = frozenset(
    {
        "table_row_alignment_uncertain",
        "verify_table_rows",
    }
)
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
        choices=(
            "json",
            "review-packet",
            "review-jsonl",
            "decision-template",
            "agent-review-prompt-jsonl",
            "messages-jsonl",
            "training-jsonl",
        ),
        default="json",
        help=(
            "Output format. JSON is stable for automation; review-packet is a "
            "human-readable queue of candidate findings, evidence, and links; "
            "review-jsonl emits one candidate per line; decision-template emits "
            "a compact editable import template; agent-review-prompt-jsonl emits "
            "one structured independent-review task per candidate; messages-jsonl "
            "emits fine-tuning-compatible rows for training-ready samples; "
            "training-jsonl keeps messages plus traceable sample metadata."
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
        include_review_packet=args.format
        in {
            "review-packet",
            "review-jsonl",
            "decision-template",
            "agent-review-prompt-jsonl",
        },
        include_training_export=args.format in {"messages-jsonl", "training-jsonl"},
        include_training_metadata=args.format == "training-jsonl",
    )
    if args.format == "review-packet":
        output = render_review_packet_summary(summary) + "\n"
    elif args.format == "review-jsonl":
        output = render_review_jsonl_summary(summary)
    elif args.format == "decision-template":
        output = render_decision_template_summary(summary)
    elif args.format == "agent-review-prompt-jsonl":
        output = render_agent_review_prompt_jsonl_summary(summary)
    elif args.format == "messages-jsonl":
        output = render_messages_jsonl_summary(summary)
    elif args.format == "training-jsonl":
        output = render_training_jsonl_summary(summary)
    else:
        output = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    write_stdout(output)
    if summary["status"] == "fail":
        raise SystemExit(1)


def write_stdout(output: str) -> None:
    try:
        sys.stdout.write(output)
    except BrokenPipeError as exc:
        with contextlib.suppress(OSError):
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
            os.close(devnull)
        raise SystemExit(0) from exc


def check_goal_dataset_quality(
    *,
    collection_id: str,
    goal_ids: tuple[str, ...] = DEFAULT_GOAL_IDS,
    api_base_url: str | None = None,
    require_training_ready: bool = False,
    include_review_packet: bool = False,
    include_training_export: bool = False,
    include_training_metadata: bool = False,
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
                include_metadata=include_training_metadata,
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
            _training_message_failure_detail(training_ready_items),
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
        "top_error_categories": _mapping_list(quality.get("top_error_categories")),
        "top_issue_types": _mapping_list(quality.get("top_issue_types")),
        "top_review_reasons": _mapping_list(quality.get("top_review_reasons")),
        "top_system_warnings": _mapping_list(quality.get("top_system_warnings")),
        "optimization_breakdown": dict(
            _mapping(quality.get("optimization_breakdown"))
        ),
        "top_variable_issue_types": _mapping_list(
            quality.get("top_variable_issue_types")
        ),
        "top_outcome_issue_types": _mapping_list(
            quality.get("top_outcome_issue_types")
        ),
        "top_direction_issue_types": _mapping_list(
            quality.get("top_direction_issue_types")
        ),
        "top_evidence_role_issue_types": _mapping_list(
            quality.get("top_evidence_role_issue_types")
        ),
        "top_variable_review_reasons": _mapping_list(
            quality.get("top_variable_review_reasons")
        ),
        "top_outcome_review_reasons": _mapping_list(
            quality.get("top_outcome_review_reasons")
        ),
        "top_direction_review_reasons": _mapping_list(
            quality.get("top_direction_review_reasons")
        ),
        "top_evidence_role_review_reasons": _mapping_list(
            quality.get("top_evidence_role_review_reasons")
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
        protocol_readiness = _protocol_readiness_for_item(item)
        acceptance_gate = _acceptance_gate_for_item(
            item,
            prediction=prediction,
            review_action=review_action,
            protocol_readiness=protocol_readiness,
        )
        decision_hint = _review_decision_hint(
            acceptance_gate=acceptance_gate,
            protocol_readiness=protocol_readiness,
            recommended_action_code=_text(review_action.get("code")),
        )
        candidates.append(
            {
                "sample_id": _text(item.get("sample_id")),
                "finding_id": finding_id,
                "claim_id": _text(item.get("claim_id")),
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
                "protocol_readiness": protocol_readiness,
                "acceptance_gate": acceptance_gate,
                "review_decision_hint": decision_hint,
                "suggested_target": {
                    "source": _text(expert_target.get("source")),
                    "review_status": _text(expert_target.get("review_status")),
                    "issue_type": _text(expert_target.get("issue_type")),
                    "statement": _training_target_statement(
                        _text(expert_target.get("statement"))
                    ),
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


def build_goal_training_message_export(
    dataset: dict[str, Any],
    *,
    include_metadata: bool = False,
) -> dict[str, Any]:
    rows = []
    for item in _mapping_list(dataset.get("items")):
        if _text(item.get("dataset_use_status")) != "training_ready":
            continue
        if not _has_fine_tuning_messages(item):
            continue
        row = {
            "messages": [
                {
                    "role": _text(message.get("role")),
                    "content": _text(message.get("content")),
                }
                for message in _mapping_list(item.get("training_messages"))
                if _text(message.get("role")) and _text(message.get("content"))
            ]
        }
        if include_metadata:
            row["metadata"] = _training_export_metadata(dataset, item)
        rows.append(row)
    return {
        "goal_id": _text(dataset.get("scope_id")),
        "row_count": len(rows),
        "rows": rows,
    }


def _training_export_metadata(
    dataset: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    target = _mapping(item.get("expert_target"))
    prediction = _mapping(item.get("system_prediction"))
    evidence_refs = _mapping_list(item.get("training_evidence_refs"))
    return {
        "collection_id": _text(dataset.get("collection_id")),
        "scope_type": _text(dataset.get("scope_type")),
        "goal_id": _text(dataset.get("scope_id")),
        "sample_id": _text(item.get("sample_id")),
        "finding_id": _text(item.get("finding_id")),
        "claim_id": _text(item.get("claim_id")),
        "label_status": _text(item.get("label_status")),
        "dataset_use_status": _text(item.get("dataset_use_status")),
        "trace_status": _text(item.get("trace_status")),
        "reviewer": _text(target.get("reviewer")),
        "review_status": _text(target.get("review_status")),
        "issue_type": _text(target.get("issue_type")),
        "support_grade": _text(
            target.get("support_grade") or prediction.get("support_grade")
        ),
        "generalization_status": _text(
            target.get("generalization_status")
            or prediction.get("generalization_status")
        ),
        "evidence_ref_ids": _text_list(
            target.get("evidence_ref_ids")
            or [record.get("evidence_ref_id") for record in evidence_refs]
        ),
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
                    f"  {index}. {_text(candidate.get('statement')) or 'n/a'}",
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
            acceptance_gate = _mapping(candidate.get("acceptance_gate"))
            if acceptance_gate:
                lines.append(
                    "     acceptance gate: "
                    f"{_text(acceptance_gate.get('status')) or 'n/a'}; "
                    f"accept_allowed={str(bool(acceptance_gate.get('accept_allowed'))).lower()}"
                )
                review_checks = _text_list(acceptance_gate.get("review_checks"))
                if review_checks:
                    lines.append(f"     expert checks: {_join(review_checks)}")
            decision_hint = _mapping(candidate.get("review_decision_hint"))
            if decision_hint:
                lines.append(
                    f"     decision hint: {_text(decision_hint.get('summary'))}"
                )
                blocked_reasons = _text_list(
                    decision_hint.get("why_accept_blocked")
                )
                if blocked_reasons:
                    lines.append(
                        f"     why accept blocked: {_join(blocked_reasons)}"
                    )
            review_reasons = _text_list(candidate.get("review_reasons"))
            warnings = _text_list(candidate.get("warnings"))
            if review_reasons:
                lines.append(f"     review reasons: {_join(review_reasons)}")
            if warnings:
                lines.append(f"     warnings: {_join(warnings)}")
            protocol_readiness = _mapping(candidate.get("protocol_readiness"))
            readiness_status = _text(protocol_readiness.get("status"))
            blocking_missing = _text_list(protocol_readiness.get("blocking_missing"))
            if blocking_missing:
                lines.append(
                    f"     protocol readiness gaps: {_join(blocking_missing)}"
                )
            elif readiness_status:
                lines.append(f"     protocol readiness: {readiness_status}")
            if _text(candidate.get("scope_summary")):
                lines.append(f"     scope: {_clip(candidate.get('scope_summary'), 220)}")
            suggested = _mapping(candidate.get("suggested_target"))
            if suggested:
                lines.append(
                    "     suggested target: "
                    f"{_text(suggested.get('statement')) or 'n/a'}"
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
                            f"          open: {_short_review_href(record.get('href'))}",
                        ]
                    )
                    table_audit = _mapping(record.get("table_audit"))
                    if table_audit:
                        columns = _text_list(table_audit.get("columns"))
                        if columns:
                            lines.append(f"          table columns: {_join(columns)}")
                        for row_index, table_row in enumerate(
                            _mapping_list(table_audit.get("relevant_rows")),
                            start=1,
                        ):
                            row_text = _table_row_text(table_row, columns)
                            if row_text:
                                lines.append(
                                    f"          table row {row_index}: {_clip(row_text, 260)}"
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
                    "claim_id": _text(candidate.get("claim_id")),
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
                    "protocol_readiness": dict(
                        _mapping(candidate.get("protocol_readiness"))
                    ),
                    "acceptance_gate": dict(
                        _mapping(candidate.get("acceptance_gate"))
                    ),
                    "review_decision_hint": dict(
                        _mapping(candidate.get("review_decision_hint"))
                    ),
                    "action": "skip",
                    "allowed_actions": list(REVIEW_ACTION_OPTIONS),
                    "issue_type": "",
                    "reject_issue_options": list(REJECT_ISSUE_OPTIONS),
                    "expert_note": "",
                    "expert_note_required": _expert_note_required(
                        _text(candidate.get("recommended_action_code"))
                    ),
                    "expert_note_prompt": _expert_note_prompt(
                        _text(candidate.get("recommended_action_code"))
                    ),
                    "suggested_target": dict(
                        _mapping(candidate.get("suggested_target"))
                    ),
                    "evidence": _mapping_list(candidate.get("evidence")),
                }
            )
    return _jsonl(rows)


def render_decision_template_summary(summary: dict[str, Any]) -> str:
    rows = []
    collection_id = _text(summary.get("collection_id"))
    for goal in _mapping_list(summary.get("goals")):
        packet = _mapping(goal.get("review_packet"))
        goal_id = _text(packet.get("goal_id")) or _text(goal.get("goal_id"))
        for candidate in _mapping_list(packet.get("candidates")):
            evidence = _mapping_list(candidate.get("evidence"))
            suggested = _mapping(candidate.get("suggested_target"))
            evidence_ref_ids = [
                ref_id
                for record in evidence
                if (ref_id := _text(record.get("evidence_ref_id")))
            ]
            evidence_summary = [_decision_template_evidence(record) for record in evidence]
            rows.append(
                {
                    "collection_id": collection_id,
                    "goal_id": goal_id,
                    "finding_id": _text(candidate.get("finding_id")),
                    "claim_id": _text(candidate.get("claim_id")),
                    "action": "skip",
                    "issue_type": "",
                    "expert_note": "",
                    "expert_note_required": _expert_note_required(
                        _text(candidate.get("recommended_action_code"))
                    ),
                    "expert_note_prompt": _expert_note_prompt(
                        _text(candidate.get("recommended_action_code"))
                    ),
                    "statement": _text(candidate.get("statement")),
                    "variables": _text_list(candidate.get("variables")),
                    "outcomes": _text_list(candidate.get("outcomes")),
                    "direction": _text(candidate.get("direction")),
                    "support_grade": _text(candidate.get("support_grade")),
                    "recommended_action_code": _text(
                        candidate.get("recommended_action_code")
                    ),
                    "review_reasons": _text_list(candidate.get("review_reasons")),
                    "acceptance_gate": dict(
                        _mapping(candidate.get("acceptance_gate"))
                    ),
                    "review_decision_hint": dict(
                        _mapping(candidate.get("review_decision_hint"))
                    ),
                    "protocol_blocking_missing": _text_list(
                        _mapping(candidate.get("protocol_readiness")).get(
                            "blocking_missing"
                        )
                    ),
                    "curated_evidence_ref_ids": evidence_ref_ids,
                    "evidence": evidence_summary,
                    "suggested_target": {
                        "statement": _training_target_statement(
                            suggested.get("statement")
                            or candidate.get("statement")
                        ),
                        "status": _text(suggested.get("status")) or "limited",
                        "support_grade": _text(
                            suggested.get("support_grade")
                            or candidate.get("support_grade")
                        ),
                        "review_status": _text(suggested.get("review_status"))
                        or "accepted",
                        "variables": _text_list(
                            suggested.get("variables")
                            or candidate.get("variables")
                        ),
                        "mediators": _text_list(
                            suggested.get("mediators")
                            or candidate.get("mediators")
                        ),
                        "outcomes": _text_list(
                            suggested.get("outcomes")
                            or candidate.get("outcomes")
                        ),
                        "direction": _text(
                            suggested.get("direction")
                            or candidate.get("direction")
                        ),
                        "scope_summary": _text(
                            suggested.get("scope_summary")
                            or candidate.get("scope_summary")
                        ),
                        "evidence_ref_ids": evidence_ref_ids,
                    },
                }
            )
    return _jsonl(rows)


def _expert_note_required(action_code: str) -> bool:
    return action_code in REVIEW_RISK_FLAGS


def _expert_note_prompt(action_code: str) -> str:
    return EXPERT_NOTE_PROMPTS.get(action_code, "")


def _training_target_statement(value: Any) -> str:
    statement = _text(value)
    if not statement:
        return ""
    return statement.replace(f" {TABLE_ROW_REVIEW_PROMPT}", "").replace(
        TABLE_ROW_REVIEW_PROMPT,
        "",
    ).strip()


def render_agent_review_prompt_jsonl_summary(summary: dict[str, Any]) -> str:
    rows = []
    collection_id = _text(summary.get("collection_id"))
    for goal in _mapping_list(summary.get("goals")):
        packet = _mapping(goal.get("review_packet"))
        goal_id = _text(packet.get("goal_id")) or _text(goal.get("goal_id"))
        for candidate in _mapping_list(packet.get("candidates")):
            rows.append(
                {
                    "task": "review_lens_research_finding",
                    "collection_id": collection_id,
                    "goal_id": goal_id,
                    "finding_id": _text(candidate.get("finding_id")),
                    "claim_id": _text(candidate.get("claim_id")),
                    "open_url": _text(candidate.get("open_url"))
                    or _text(packet.get("review_url")),
                    "reviewer_role": "independent_materials_science_reviewer",
                    "instructions": [
                        (
                            "Judge whether the cited evidence supports the finding, "
                            "including variable, outcome, direction, scope, and "
                            "paper-level limitations."
                        ),
                        (
                            "Return an agent_review object only; do not change "
                            "top-level action or mark human_confirmed."
                        ),
                        (
                            "Use recommendation=accept only when the evidence and "
                            "acceptance gate checks pass; use correct for a narrower "
                            "evidence-grounded target; use reject when evidence does "
                            "not support the finding; use unclear when source review "
                            "is still insufficient."
                        ),
                    ],
                    "finding": _agent_review_finding(candidate),
                    "acceptance_gate": dict(_mapping(candidate.get("acceptance_gate"))),
                    "review_decision_hint": dict(
                        _mapping(candidate.get("review_decision_hint"))
                    ),
                    "protocol_readiness": dict(
                        _mapping(candidate.get("protocol_readiness"))
                    ),
                    "evidence": _mapping_list(candidate.get("evidence")),
                    "suggested_target": dict(_mapping(candidate.get("suggested_target"))),
                    "output_schema": {
                        "agent_review": {
                            "reviewer": "ai-reviewer-<name>",
                            "recommendation": "accept|reject|correct|unclear|skip",
                            "issue_type": (
                                "none|evidence_not_grounded|missing_evidence|"
                                "insufficient_evidence|wrong_variable|wrong_outcome|"
                                "wrong_direction|wrong_context|wrong_relation|"
                                "overclaim|unclear_statement|other"
                            ),
                            "note": "short evidence-grounded rationale",
                            "suggested_target": {
                                "statement": "required for correct",
                                "variables": ["..."],
                                "mediators": ["..."],
                                "outcomes": ["..."],
                                "direction": "...",
                                "scope_summary": "...",
                                "support_grade": "strong|partial|weak|conflicted",
                                "evidence_ref_ids": ["..."],
                            },
                            "human_confirmed": False,
                        }
                    },
                }
            )
    return _jsonl(rows)


def _agent_review_finding(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "statement": _text(candidate.get("statement")),
        "variables": _text_list(candidate.get("variables")),
        "mediators": _text_list(candidate.get("mediators")),
        "outcomes": _text_list(candidate.get("outcomes")),
        "direction": _text(candidate.get("direction")),
        "scope_summary": _text(candidate.get("scope_summary")),
        "support_grade": _text(candidate.get("support_grade")),
        "review_status": _text(candidate.get("review_status")),
        "review_reasons": _text_list(candidate.get("review_reasons")),
        "warnings": _text_list(candidate.get("warnings")),
        "recommended_action_code": _text(candidate.get("recommended_action_code")),
        "recommended_action": _text(candidate.get("recommended_action")),
    }


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


def _review_decision_hint(
    *,
    acceptance_gate: dict[str, Any],
    protocol_readiness: dict[str, Any],
    recommended_action_code: str,
) -> dict[str, Any]:
    accept_allowed = bool(acceptance_gate.get("accept_allowed"))
    review_checks = _text_list(acceptance_gate.get("review_checks"))
    accept_blockers = _text_list(acceptance_gate.get("accept_blockers"))
    blocking_missing = (
        _text_list(acceptance_gate.get("blocking_missing"))
        or _text_list(protocol_readiness.get("blocking_missing"))
    )
    if not accept_allowed:
        reasons = []
        if accept_blockers:
            reasons.append(f"accept_blockers={_join(accept_blockers)}")
        if blocking_missing:
            reasons.append(f"blocking_missing={_join(blocking_missing)}")
        if not reasons:
            reasons.append("acceptance_gate blocks direct accept")
        return {
            "summary": (
                "Do not accept directly; correct the row or reject it after "
                "source review."
            ),
            "preferred_next_action": "correct_or_reject",
            "allowed_actions": ["reject", "correct", "skip"],
            "blocked_actions": ["accept"],
            "why_accept_blocked": reasons,
            "required_checks": review_checks,
            "import_note": "accept is rejected while acceptance_gate.accept_allowed=false",
        }
    action_summaries = {
        "accept_as_paper_level": (
            "Accept only as paper-level evidence after checking the quote; "
            "correct if the scope should be narrower."
        ),
        "review_table_rows": (
            "Verify the selected table rows and then accept or correct the "
            "finding."
        ),
        "review_table_variables": (
            "Check whether other table variables changed; correct if this is "
            "not a single-variable effect."
        ),
        "check_mechanism_requirement": (
            "Decide whether mechanism evidence is required; accept only if the "
            "final scope matches that decision."
        ),
        "resolve_conflict": (
            "Resolve the conflicting evidence direction before accepting."
        ),
    }
    summary = action_summaries.get(
        recommended_action_code,
        "Accept, reject, or correct after checking the cited evidence.",
    )
    preferred_next_action = (
        "verify_then_accept_or_correct"
        if recommended_action_code
        in {"review_table_rows", "review_table_variables", "check_mechanism_requirement"}
        else "accept_after_checks"
    )
    return {
        "summary": summary,
        "preferred_next_action": preferred_next_action,
        "allowed_actions": list(REVIEW_ACTION_OPTIONS),
        "blocked_actions": [],
        "why_accept_blocked": [],
        "required_checks": review_checks,
        "import_note": "accept imports only after the reviewer changes action from skip",
    }


def render_messages_jsonl_summary(summary: dict[str, Any]) -> str:
    rows = []
    for goal in _mapping_list(summary.get("goals")):
        export = _mapping(goal.get("training_export"))
        rows.extend(_mapping_list(export.get("rows")))
    return _jsonl(rows)


def render_training_jsonl_summary(summary: dict[str, Any]) -> str:
    rows = []
    for goal in _mapping_list(summary.get("goals")):
        export = _mapping(goal.get("training_export"))
        for row in _mapping_list(export.get("rows")):
            if isinstance(row.get("metadata"), dict):
                rows.append(row)
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
    return not _training_message_diagnostic(item)


def _training_message_diagnostic(item: dict[str, Any]) -> list[str]:
    expected = _training_message_expected_payload(item)
    missing_expected = _training_message_missing_expected_fields(expected)
    if missing_expected:
        return [f"missing_expected_{field}" for field in missing_expected]
    messages = _mapping_list(item.get("training_messages"))
    if len(messages) < 2:
        return ["missing_message_pair"]
    if _text(messages[0].get("role")) != "user" or not _text(
        messages[0].get("content")
    ):
        return ["invalid_user_message"]
    if _text(messages[-1].get("role")) != "assistant":
        return ["missing_assistant_message"]
    assistant_content = _text(messages[-1].get("content"))
    if not assistant_content:
        return ["missing_assistant_content"]
    try:
        assistant_payload = json.loads(assistant_content)
    except json.JSONDecodeError:
        return ["invalid_assistant_json"]
    if not isinstance(assistant_payload, dict):
        return ["invalid_assistant_json_object"]
    return [
        f"mismatched_assistant_{field}"
        for field in _training_message_payload_mismatch_fields(
            assistant_payload,
            expected,
        )
    ]


def _training_message_expected_payload(item: dict[str, Any]) -> dict[str, Any]:
    expert_target = _mapping(item.get("expert_target"))
    prediction = _mapping(item.get("system_prediction"))
    evidence = _mapping_list(item.get("training_evidence_refs"))
    return {
        "statement": _text(
            expert_target.get("statement") or prediction.get("statement")
        ),
        "variables": _text_list(
            expert_target.get("variables") or prediction.get("variables")
        ),
        "outcomes": _text_list(
            expert_target.get("outcomes") or prediction.get("outcomes")
        ),
        "direction": _text(
            expert_target.get("direction") or prediction.get("direction")
        ),
        "scope_summary": _text(
            expert_target.get("scope_summary") or prediction.get("scope_summary")
        ),
        "support_grade": _text(
            expert_target.get("support_grade") or prediction.get("support_grade")
        ),
        "generalization_status": _text(
            expert_target.get("generalization_status")
            or prediction.get("generalization_status")
        ),
        "evidence_ref_ids": _text_list(
            expert_target.get("evidence_ref_ids")
            or [record.get("evidence_ref_id") for record in evidence]
        ),
    }


def _training_message_expected_payload_is_complete(
    expected: dict[str, Any],
) -> bool:
    return not _training_message_missing_expected_fields(expected)


def _training_message_missing_expected_fields(
    expected: dict[str, Any],
) -> list[str]:
    missing = []
    if not _text(expected.get("statement")):
        missing.append("statement")
    if not _text_list(expected.get("variables")):
        missing.append("variables")
    if not _text_list(expected.get("outcomes")):
        missing.append("outcomes")
    if not (
        _text(expected.get("direction"))
        or _text(expected.get("scope_summary"))
    ):
        missing.append("direction_or_scope")
    if not _text(expected.get("support_grade")):
        missing.append("support_grade")
    if not _text(expected.get("generalization_status")):
        missing.append("generalization_status")
    if not _text_list(expected.get("evidence_ref_ids")):
        missing.append("evidence_ref_ids")
    return missing


def _training_message_payload_matches_expected(
    assistant_payload: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    return not _training_message_payload_mismatch_fields(assistant_payload, expected)


def _training_message_payload_mismatch_fields(
    assistant_payload: dict[str, Any],
    expected: dict[str, Any],
) -> list[str]:
    mismatches = []
    if _normalized_text(assistant_payload.get("statement")) != _normalized_text(
        expected.get("statement")
    ):
        mismatches.append("statement")
    if _normalized_text_list(assistant_payload.get("variables")) != _normalized_text_list(
        expected.get("variables")
    ):
        mismatches.append("variables")
    if _normalized_text_list(assistant_payload.get("outcomes")) != _normalized_text_list(
        expected.get("outcomes")
    ):
        mismatches.append("outcomes")
    if _text(expected.get("direction")) and _normalized_text(
        assistant_payload.get("direction")
    ) != _normalized_text(expected.get("direction")):
        mismatches.append("direction")
    if _text(expected.get("scope_summary")) and _normalized_text(
        assistant_payload.get("scope_summary")
    ) != _normalized_text(expected.get("scope_summary")):
        mismatches.append("scope_summary")
    if _normalized_text(assistant_payload.get("support_grade")) != _normalized_text(
        expected.get("support_grade")
    ):
        mismatches.append("support_grade")
    if _normalized_text(
        assistant_payload.get("generalization_status")
    ) != _normalized_text(expected.get("generalization_status")):
        mismatches.append("generalization_status")
    if _normalized_text_list(
        assistant_payload.get("evidence_ref_ids")
    ) != _normalized_text_list(expected.get("evidence_ref_ids")):
        mismatches.append("evidence_ref_ids")
    return mismatches


def _has_protocol_design_inputs(item: dict[str, Any]) -> bool:
    return _protocol_readiness_for_item(item)["status"] == "protocol_ready"


def _protocol_readiness_for_item(item: dict[str, Any]) -> dict[str, Any]:
    target = _mapping(item.get("expert_target"))
    prediction = _mapping(item.get("system_prediction"))
    dataset_use_status = _text(item.get("dataset_use_status"))
    evidence_records = (
        _mapping_list(item.get("training_evidence_refs"))
        or _mapping_list(item.get("evidence_refs"))
        or _mapping_list(item.get("input_blocks"))
    )
    status = _text(target.get("status") or prediction.get("status")).lower()
    support_grade = _text(
        target.get("support_grade") or prediction.get("support_grade")
    ).lower()
    checks = {
        "expert_review_decision": dataset_use_status == "training_ready",
        "training_messages": (
            _has_fine_tuning_messages(item)
            if dataset_use_status == "training_ready"
            else True
        ),
        "statement": bool(
            _text(target.get("statement") or prediction.get("statement"))
        ),
        "variables": bool(
            _text_list(target.get("variables"))
            or _text_list(prediction.get("variables"))
        ),
        "outcomes": bool(
            _text_list(target.get("outcomes"))
            or _text_list(prediction.get("outcomes"))
        ),
        "direction_or_scope": bool(
            _text(target.get("direction") or prediction.get("direction"))
            or _text(target.get("scope_summary") or prediction.get("scope_summary"))
        ),
        "support_status": status not in {"unsupported", "conflicted"},
        "support_grade": support_grade
        not in {"insufficient", "conflict", "conflicted", "weak"},
        "traceable_training_evidence": _has_traceable_evidence_records(
            evidence_records
        ),
    }
    blocking_keys = (
        "statement",
        "variables",
        "outcomes",
        "direction_or_scope",
        "support_status",
        "support_grade",
        "traceable_training_evidence",
    )
    blocking_missing = [key for key in blocking_keys if not checks[key]]
    missing = [
        key
        for key in (
            "expert_review_decision",
            "training_messages",
            *blocking_keys,
        )
        if not checks[key]
    ]
    if not missing:
        status_label = "protocol_ready"
        guidance = "Ready for traceable protocol drafting."
    elif blocking_missing:
        status_label = "needs_correction"
        guidance = (
            "Correct the missing fields or evidence before importing this row."
        )
    else:
        status_label = "ready_after_review"
        guidance = (
            "Accept only after expert review confirms the finding and evidence."
        )
    return {
        "status": status_label,
        "ready_after_review": not blocking_missing,
        "missing": missing,
        "blocking_missing": blocking_missing,
        "checks": checks,
        "guidance": guidance,
    }


def _acceptance_gate_for_item(
    item: dict[str, Any],
    *,
    prediction: dict[str, Any],
    review_action: dict[str, Any],
    protocol_readiness: dict[str, Any],
) -> dict[str, Any]:
    existing = _mapping(item.get("acceptance_gate"))
    if existing:
        return dict(existing)
    dataset_use_status = _text(item.get("dataset_use_status"))
    blocking_missing = _text_list(protocol_readiness.get("blocking_missing"))
    accept_blockers = _accept_blockers(
        prediction=prediction,
        review_action=review_action,
    )
    review_checks = _acceptance_review_checks(
        prediction=prediction,
        review_action=review_action,
    )
    if dataset_use_status == "training_ready":
        status = "accepted"
        accept_allowed = False
        requires_correction = False
        guidance = "Already accepted for training use."
    elif accept_blockers:
        status = "correction_required"
        accept_allowed = False
        requires_correction = True
        guidance = "Do not accept directly; correct or reject the table alignment risk first."
    elif blocking_missing:
        status = "correction_required"
        accept_allowed = False
        requires_correction = True
        guidance = "Do not accept directly; correct or reject the blocking gaps first."
    else:
        status = "review_required"
        accept_allowed = True
        requires_correction = False
        guidance = "Accept only after the listed checks and source evidence match."
    return {
        "status": status,
        "accept_allowed": accept_allowed,
        "requires_correction": requires_correction,
        "blocking_missing": blocking_missing,
        "accept_blockers": accept_blockers,
        "review_checks": review_checks,
        "recommended_action_code": _text(review_action.get("code")),
        "guidance": guidance,
    }


def _accept_blockers(
    *,
    prediction: dict[str, Any],
    review_action: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for value in [
        _text(review_action.get("code")),
        *_text_list(prediction.get("review_reasons")),
        *_text_list(prediction.get("warnings")),
    ]:
        if value in ACCEPT_BLOCKING_REVIEW_CODES and value not in blockers:
            blockers.append(value)
    return blockers


def _acceptance_review_checks(
    *,
    prediction: dict[str, Any],
    review_action: dict[str, Any],
) -> list[str]:
    checks: list[str] = []
    action_code = _text(review_action.get("code"))
    if action_code in ACCEPTANCE_REVIEW_CHECKS:
        checks.append(ACCEPTANCE_REVIEW_CHECKS[action_code])
    for value in [
        *_text_list(prediction.get("review_reasons")),
        *_text_list(prediction.get("warnings")),
    ]:
        if value in ACCEPTANCE_REVIEW_CHECKS:
            check = ACCEPTANCE_REVIEW_CHECKS[value]
            if check not in checks:
                checks.append(check)
    return checks


def _has_traceable_evidence_records(records: list[dict[str, Any]]) -> bool:
    return bool(records) and all(
        _text(record.get("source_ref"))
        and _text(record.get("href"))
        and (
            _text(record.get("quote"))
            or _text(record.get("source_text"))
            or _text(record.get("training_source_text"))
            or _text(record.get("text"))
        )
        for record in records
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


def _training_message_failure_detail(items: list[dict[str, Any]]) -> str:
    failures = []
    for item in items:
        diagnostic = _training_message_diagnostic(item)
        if not diagnostic:
            continue
        sample_id = _text(item.get("sample_id")) or _text(item.get("finding_id")) or "unknown"
        failures.append({"sample": sample_id, "diagnostic": diagnostic})
    if not failures:
        return "none"
    return "training_message_diagnostic=" + json.dumps(
        failures[:10],
        ensure_ascii=False,
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _review_evidence_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_ref_id": _text(record.get("evidence_ref_id")),
        "label": _text(record.get("label"))
        or _text(record.get("source_label"))
        or _text(record.get("source_kind")),
        "source_ref": _text(record.get("source_ref")),
        "page": _text(record.get("page")),
        "href": _text(record.get("href")),
        "value_summary": _text(record.get("value_summary")),
        "table_audit": _mapping(record.get("table_audit")) or None,
        "quote": _text(record.get("quote"))
        or _text(record.get("source_text"))
        or _text(record.get("training_source_text"))
        or _text(record.get("text")),
    }


def _table_row_text(row: dict[str, Any], columns: list[str]) -> str:
    cells_value = row.get("cells")
    cells = _mapping(cells_value)
    if cells:
        return "; ".join(
            f"{key}: {value}"
            for key, value in cells.items()
            if _text(key) and _text(value)
        )
    if isinstance(cells_value, list):
        values = _text_list(cells_value)
        if values:
            return "; ".join(
                f"{columns[index] if index < len(columns) else f'cell {index + 1}'}: {value}"
                for index, value in enumerate(values)
                if value
            )
    return "; ".join(
        f"{key}: {value}"
        for key, value in row.items()
        if key != "cells" and _text(key) and _text(value)
    )


def _decision_template_evidence(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_ref_id": _text(record.get("evidence_ref_id")),
        "label": _text(record.get("label")),
        "source_ref": _text(record.get("source_ref")),
        "page": _text(record.get("page")),
        "value_summary": _text(record.get("value_summary")),
        "table_audit": _mapping(record.get("table_audit")) or None,
        "quote": _text(record.get("quote")),
        "open": _short_review_href(record.get("href")),
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


def _short_review_href(value: Any) -> str:
    href = _text(value)
    if not href:
        return "n/a"
    parsed = urlsplit(href)
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "quote"
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalized_text(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _normalized_text_list(value: Any) -> tuple[str, ...]:
    return tuple(_normalized_text(item) for item in _text_list(value))


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
