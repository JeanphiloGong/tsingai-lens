from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from application.evaluation import (
    ResearchUnderstandingFeedbackService,
    ResearchUnderstandingReviewImportService,
)
from controllers.dependencies.auth import require_current_user
from controllers.schemas.core.research_understanding import (
    ResearchUnderstandingCurationCreateRequest,
    ResearchUnderstandingCurationListResponse,
    ResearchUnderstandingCurationResponse,
    ResearchUnderstandingFeedbackCreateRequest,
    ResearchUnderstandingFeedbackListResponse,
    ResearchUnderstandingFeedbackResponse,
    ResearchUnderstandingDatasetExportFormat,
    ResearchUnderstandingDatasetLabelStatus,
    ResearchUnderstandingDatasetResponse,
    ResearchUnderstandingDatasetUseStatus,
    ResearchUnderstandingGoldDraftResponse,
    ResearchUnderstandingReviewDecisionImportRequest,
    ResearchUnderstandingReviewDecisionImportResponse,
)
from domain.evaluation import ResearchUnderstandingCuration, ResearchUnderstandingFeedback

router = APIRouter(prefix="/collections", tags=["research-understanding-feedback"])
feedback_service = ResearchUnderstandingFeedbackService()
review_import_service = ResearchUnderstandingReviewImportService(feedback_service)
REVIEW_ACTION_OPTIONS = ("accept", "reject", "correct", "skip")
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


def _dataset_jsonl_response(
    response: ResearchUnderstandingDatasetResponse,
    *,
    messages_only: bool = False,
    include_training_metadata: bool = False,
) -> Response:
    rows: list[dict[str, Any]]
    if messages_only:
        rows = [
            _training_jsonl_row(response.collection_id, item)
            if include_training_metadata
            else {"messages": item.training_messages}
            for item in response.items
            if item.training_messages
        ]
    else:
        rows = [item.model_dump(mode="json") for item in response.items]
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if body:
        body += "\n"
    return Response(content=body, media_type="application/x-ndjson")


def _training_jsonl_row(
    collection_id: str,
    item: Any,
) -> dict[str, Any]:
    target = item.expert_target or {}
    prediction = item.system_prediction or {}
    evidence_refs = item.training_evidence_refs or item.evidence_refs
    return {
        "messages": item.training_messages,
        "metadata": {
            "collection_id": collection_id,
            "scope_type": item.scope_type,
            "goal_id": item.scope_id if item.scope_type == "goal" else "",
            "scope_id": item.scope_id,
            "sample_id": item.sample_id,
            "finding_id": item.finding_id,
            "claim_id": item.claim_id or "",
            "label_status": item.label_status,
            "dataset_use_status": item.dataset_use_status,
            "trace_status": item.trace_status,
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
            "evidence_ref_ids": _strings(
                target.get("evidence_ref_ids")
                or [record.get("evidence_ref_id") for record in evidence_refs]
            ),
        },
    }


def _dataset_review_jsonl_response(
    response: ResearchUnderstandingDatasetResponse,
) -> Response:
    rows = [
        _review_jsonl_row(response.collection_id, item)
        for item in response.items
        if item.dataset_use_status == "review_candidate"
    ]
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if body:
        body += "\n"
    return Response(content=body, media_type="application/x-ndjson")


def _dataset_decision_template_response(
    response: ResearchUnderstandingDatasetResponse,
) -> Response:
    rows = [
        _decision_template_row(_review_jsonl_row(response.collection_id, item))
        for item in response.items
        if item.dataset_use_status == "review_candidate"
    ]
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if body:
        body += "\n"
    return Response(content=body, media_type="application/x-ndjson")


def _dataset_agent_review_prompt_response(
    response: ResearchUnderstandingDatasetResponse,
) -> Response:
    rows = [
        _agent_review_prompt_row(_review_jsonl_row(response.collection_id, item))
        for item in response.items
        if item.dataset_use_status == "review_candidate"
    ]
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if body:
        body += "\n"
    return Response(content=body, media_type="application/x-ndjson")


def _agent_review_prompt_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "review_lens_research_finding",
        "collection_id": row["collection_id"],
        "goal_id": row["goal_id"],
        "scope_type": row["scope_type"],
        "scope_id": row["scope_id"],
        "sample_id": row["sample_id"],
        "finding_id": row["finding_id"],
        "claim_id": row["claim_id"],
        "reviewer_role": "independent_materials_science_reviewer",
        "instructions": [
            (
                "Judge whether the cited evidence supports the finding, including "
                "variable, outcome, direction, scope, and paper-level limitations."
            ),
            (
                "Return an agent_review object only; do not change top-level "
                "action or mark human_confirmed."
            ),
            (
                "Use recommendation=accept only when the evidence and acceptance "
                "gate checks pass; use correct for a narrower evidence-grounded "
                "target; use reject when evidence does not support the finding; "
                "use unclear when source review is still insufficient."
            ),
        ],
        "finding": {
            "statement": row["statement"],
            "variables": row["variables"],
            "mediators": row["mediators"],
            "outcomes": row["outcomes"],
            "direction": row["direction"],
            "scope_summary": row["scope_summary"],
            "support_grade": row["support_grade"],
            "review_status": row["review_status"],
            "review_reasons": row["review_reasons"],
            "warnings": row["warnings"],
            "recommended_action_code": row["recommended_action_code"],
            "recommended_action": row["recommended_action"],
        },
        "acceptance_gate": row["acceptance_gate"],
        "protocol_readiness": row["protocol_readiness"],
        "evidence": row["evidence"],
        "suggested_target": row["suggested_target"],
        "output_schema": {
            "agent_review": {
                "reviewer": "ai-reviewer-<name>",
                "recommendation": "accept|reject|correct|unclear|skip",
                "issue_type": "none|" + "|".join(REJECT_ISSUE_OPTIONS),
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


def _decision_template_row(row: dict[str, Any]) -> dict[str, Any]:
    evidence_ref_ids = [
        ref_id for record in row["evidence"] if (ref_id := _text(record.get("evidence_ref_id")))
    ]
    suggested = row["suggested_target"] if isinstance(row["suggested_target"], dict) else {}
    return {
        "collection_id": row["collection_id"],
        "goal_id": row["goal_id"],
        "finding_id": row["finding_id"],
        "claim_id": row["claim_id"],
        "action": "skip",
        "issue_type": "",
        "expert_note": "",
        "statement": row["statement"],
        "variables": row["variables"],
        "outcomes": row["outcomes"],
        "direction": row["direction"],
        "support_grade": row["support_grade"],
        "recommended_action_code": row["recommended_action_code"],
        "review_reasons": row["review_reasons"],
        "acceptance_gate": dict(row["acceptance_gate"]),
        "protocol_blocking_missing": _strings(
            row["protocol_readiness"].get("blocking_missing")
        ),
        "curated_evidence_ref_ids": evidence_ref_ids,
        "evidence": [_decision_template_evidence(record) for record in row["evidence"]],
        "suggested_target": {
            "statement": _text(suggested.get("statement") or row["statement"]),
            "status": _text(suggested.get("status")) or "limited",
            "support_grade": _text(suggested.get("support_grade") or row["support_grade"]),
            "review_status": _text(suggested.get("review_status")) or "accepted",
            "variables": _strings(suggested.get("variables") or row["variables"]),
            "mediators": _strings(suggested.get("mediators") or row["mediators"]),
            "outcomes": _strings(suggested.get("outcomes") or row["outcomes"]),
            "direction": _text(suggested.get("direction") or row["direction"]),
            "scope_summary": _text(suggested.get("scope_summary") or row["scope_summary"]),
            "evidence_ref_ids": evidence_ref_ids,
        },
    }


def _dataset_review_packet_response(
    response: ResearchUnderstandingDatasetResponse,
) -> Response:
    rows = [
        _review_jsonl_row(response.collection_id, item)
        for item in response.items
        if item.dataset_use_status == "review_candidate"
    ]
    lines = [
        f"Lens review packet: {response.collection_id}",
        f"Scope: {response.scope_type} {response.scope_id}",
        f"Review candidates: {len(rows)}",
        "",
        REVIEW_INSTRUCTIONS,
    ]
    for index, row in enumerate(rows, start=1):
        protocol_readiness = row["protocol_readiness"]
        evidence_records = row["evidence"]
        lines.extend(
            [
                "",
                f"{index}. {_clip(row['statement'], 240)}",
                (
                    "   fields: "
                    f"variables={_join(row['variables'])}; "
                    f"outcomes={_join(row['outcomes'])}; "
                    f"direction={row['direction'] or 'n/a'}"
                ),
                (
                    "   status: "
                    f"support={row['support_grade'] or 'n/a'}; "
                    f"review={row['review_status'] or 'n/a'}; "
                    f"trace={row['trace_status'] or 'n/a'}"
                ),
                f"   recommended action: {row['recommended_action'] or 'review evidence'}",
                (
                    "   protocol readiness: "
                    f"{protocol_readiness.get('status') or 'n/a'}"
                ),
            ]
        )
        acceptance_gate = row["acceptance_gate"]
        lines.append(
            "   acceptance gate: "
            f"{acceptance_gate.get('status') or 'n/a'}; "
            f"accept_allowed={str(bool(acceptance_gate.get('accept_allowed'))).lower()}"
        )
        review_checks = _strings(acceptance_gate.get("review_checks"))
        if review_checks:
            lines.append(f"   expert checks: {_join(review_checks)}")
        blocking_missing = _strings(protocol_readiness.get("blocking_missing"))
        if blocking_missing:
            lines.append(f"   protocol gaps: {_join(blocking_missing)}")
        if row["review_reasons"]:
            lines.append(f"   review reasons: {_join(row['review_reasons'])}")
        if row["warnings"]:
            lines.append(f"   warnings: {_join(row['warnings'])}")
        if row["scope_summary"]:
            lines.append(f"   scope: {_clip(row['scope_summary'], 220)}")
        if row["finding_id"]:
            lines.append(f"   finding_id: {row['finding_id']}")
        if row["claim_id"]:
            lines.append(f"   claim_id: {row['claim_id']}")
        if evidence_records:
            lines.append("   evidence:")
            for evidence_index, evidence in enumerate(evidence_records, start=1):
                label = evidence.get("label") or evidence.get("source_ref") or "source"
                page = evidence.get("page")
                page_text = f" / p. {page}" if page else ""
                lines.extend(
                    [
                        f"     {evidence_index}. {label}{page_text}",
                        f"        quote: {_clip(evidence.get('quote'), 360)}",
                        f"        open: {_short_review_href(evidence.get('href'))}",
                    ]
                )
    if not rows:
        lines.extend(["", "No review candidates found."])
    return Response(content="\n".join(lines) + "\n", media_type="text/plain")


def _review_jsonl_row(
    collection_id: str,
    item: Any,
) -> dict[str, Any]:
    prediction = item.system_prediction or {}
    expert_target = item.expert_target or {}
    evidence = item.training_evidence_refs or item.evidence_refs or item.input_blocks
    review_action = item.review_action or {}
    protocol_readiness = _protocol_readiness_for_item(item)
    acceptance_gate = _acceptance_gate_for_item(
        item,
        prediction=prediction,
        review_action=review_action,
        protocol_readiness=protocol_readiness,
    )
    return {
        "collection_id": collection_id,
        "goal_id": item.scope_id if item.scope_type == "goal" else "",
        "scope_type": item.scope_type,
        "scope_id": item.scope_id,
        "sample_id": item.sample_id,
        "finding_id": item.finding_id,
        "claim_id": item.claim_id or "",
        "statement": _text(prediction.get("statement"))
        or _text(expert_target.get("statement")),
        "variables": _strings(prediction.get("variables")),
        "mediators": _strings(prediction.get("mediators")),
        "outcomes": _strings(prediction.get("outcomes")),
        "direction": _text(prediction.get("direction")),
        "scope_summary": _text(prediction.get("scope_summary")),
        "support_grade": _text(prediction.get("support_grade")),
        "review_status": _text(prediction.get("review_status")),
        "presentation_bucket": item.presentation_bucket,
        "trace_status": item.trace_status,
        "review_reasons": _strings(prediction.get("review_reasons")),
        "warnings": _strings(prediction.get("warnings")),
        "recommended_action": _text(review_action.get("label")),
        "recommended_action_code": _text(review_action.get("code")),
        "review_instructions": REVIEW_INSTRUCTIONS,
        "review_risk_flags": _review_risk_flags(
            _text(review_action.get("code")),
            _strings(prediction.get("review_reasons")),
            _strings(prediction.get("warnings")),
        ),
        "protocol_readiness": protocol_readiness,
        "acceptance_gate": acceptance_gate,
        "action": "skip",
        "allowed_actions": list(REVIEW_ACTION_OPTIONS),
        "issue_type": "",
        "reject_issue_options": list(REJECT_ISSUE_OPTIONS),
        "expert_note": "",
        "suggested_target": expert_target,
        "evidence": [_review_evidence_record(record) for record in evidence],
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


def _acceptance_gate_for_item(
    item: Any,
    *,
    prediction: dict[str, Any],
    review_action: dict[str, Any],
    protocol_readiness: dict[str, Any],
) -> dict[str, Any]:
    existing = getattr(item, "acceptance_gate", None)
    if isinstance(existing, dict) and existing:
        return existing
    blocking_missing = _strings(protocol_readiness.get("blocking_missing"))
    review_checks = _acceptance_review_checks(
        prediction=prediction,
        review_action=review_action,
    )
    if _text(item.dataset_use_status) == "training_ready":
        status = "accepted"
        accept_allowed = False
        requires_correction = False
        guidance = "Already accepted for training use."
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
        "review_checks": review_checks,
        "recommended_action_code": _text(review_action.get("code")),
        "guidance": guidance,
    }


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
        *_strings(prediction.get("review_reasons")),
        *_strings(prediction.get("warnings")),
    ]:
        if value in ACCEPTANCE_REVIEW_CHECKS:
            check = ACCEPTANCE_REVIEW_CHECKS[value]
            if check not in checks:
                checks.append(check)
    return checks


def _review_evidence_record(record: dict[str, Any]) -> dict[str, Any]:
    table_audit = record.get("table_audit")
    return {
        "evidence_ref_id": _text(record.get("evidence_ref_id")),
        "label": _text(record.get("label"))
        or _text(record.get("source_label"))
        or _text(record.get("source_kind")),
        "source_ref": _text(record.get("source_ref")),
        "page": _text(record.get("page")),
        "href": _text(record.get("href")),
        "value_summary": _text(record.get("value_summary")),
        "table_audit": table_audit if isinstance(table_audit, dict) else None,
        "quote": _text(record.get("quote"))
        or _text(record.get("source_text"))
        or _text(record.get("training_source_text"))
        or _text(record.get("text")),
    }


def _decision_template_evidence(record: dict[str, Any]) -> dict[str, str]:
    return {
        "evidence_ref_id": _text(record.get("evidence_ref_id")),
        "label": _text(record.get("label")),
        "source_ref": _text(record.get("source_ref")),
        "page": _text(record.get("page")),
        "quote": _text(record.get("quote")),
        "open": _short_review_href(record.get("href")),
    }


def _protocol_readiness_for_item(item: Any) -> dict[str, Any]:
    prediction = item.system_prediction or {}
    expert_target = item.expert_target or {}
    evidence = item.training_evidence_refs or item.evidence_refs or item.input_blocks
    dataset_use_status = _text(item.dataset_use_status)
    status = _text(
        expert_target.get("status") or prediction.get("status")
    ).lower()
    support_grade = _text(
        expert_target.get("support_grade") or prediction.get("support_grade")
    ).lower()
    checks = {
        "expert_review_decision": dataset_use_status == "training_ready",
        "training_messages": True,
        "statement": bool(
            _text(expert_target.get("statement") or prediction.get("statement"))
        ),
        "variables": bool(
            _strings(expert_target.get("variables"))
            or _strings(prediction.get("variables"))
        ),
        "outcomes": bool(
            _strings(expert_target.get("outcomes"))
            or _strings(prediction.get("outcomes"))
        ),
        "direction_or_scope": bool(
            _text(expert_target.get("direction") or prediction.get("direction"))
            or _text(
                expert_target.get("scope_summary")
                or prediction.get("scope_summary")
            )
        ),
        "support_status": status not in {"unsupported", "conflicted"},
        "support_grade": support_grade
        not in {"insufficient", "conflict", "conflicted", "weak"},
        "traceable_training_evidence": _has_traceable_evidence_records(evidence),
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
        for key in ("expert_review_decision", "training_messages", *blocking_keys)
        if not checks[key]
    ]
    if not missing:
        status_label = "protocol_ready"
        guidance = "Ready for traceable protocol drafting."
    elif blocking_missing:
        status_label = "needs_correction"
        guidance = "Correct the missing fields or evidence before importing this row."
    else:
        status_label = "ready_after_review"
        guidance = "Accept only after expert review confirms the finding and evidence."
    return {
        "status": status_label,
        "ready_after_review": not blocking_missing,
        "missing": missing,
        "blocking_missing": blocking_missing,
        "checks": checks,
        "guidance": guidance,
    }


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


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _join(value: Any) -> str:
    items = value if isinstance(value, list) else []
    text = ", ".join(_text(item) for item in items if _text(item))
    return text or "n/a"


def _clip(value: Any, limit: int) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


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


@router.post(
    "/{collection_id}/research-understanding/review-decisions/import",
    response_model=ResearchUnderstandingReviewDecisionImportResponse,
    summary="批量预检或导入 research understanding 专家复核决策",
)
async def import_research_understanding_review_decisions(
    collection_id: str,
    payload: ResearchUnderstandingReviewDecisionImportRequest,
    request: Request,
) -> ResearchUnderstandingReviewDecisionImportResponse:
    reviewer = _reviewer_for_write(request, payload.reviewer)
    rows = [
        {**row, "collection_id": _text(row.get("collection_id")) or collection_id}
        for row in payload.rows
    ]
    summary = await run_in_threadpool(
        review_import_service.import_rows,
        rows=rows,
        reviewer=reviewer,
        dry_run=payload.dry_run,
        fail_on_warnings=payload.fail_on_warnings,
    )
    return ResearchUnderstandingReviewDecisionImportResponse(**summary)


@router.post(
    "/{collection_id}/research-understanding/feedback",
    response_model=ResearchUnderstandingFeedbackResponse,
    summary="记录 research understanding finding 专家反馈",
)
async def create_research_understanding_feedback(
    collection_id: str,
    payload: ResearchUnderstandingFeedbackCreateRequest,
    request: Request,
) -> ResearchUnderstandingFeedbackResponse:
    feedback = await run_in_threadpool(
        feedback_service.record_feedback,
        collection_id=collection_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        finding_id=payload.finding_id,
        claim_id=payload.claim_id,
        review_status=payload.review_status,
        issue_type=payload.issue_type,
        note=payload.note,
        reviewer=_reviewer_for_write(request, payload.reviewer),
    )
    return ResearchUnderstandingFeedbackResponse(**feedback.to_record())


@router.get(
    "/{collection_id}/research-understanding/feedback",
    response_model=ResearchUnderstandingFeedbackListResponse,
    summary="读取 research understanding finding 专家反馈",
)
async def list_research_understanding_feedback(
    collection_id: str,
    scope_type: str | None = Query(default=None, max_length=32),
    scope_id: str | None = Query(default=None, max_length=160),
    finding_id: str | None = Query(default=None, max_length=200),
    claim_id: str | None = Query(default=None, max_length=200),
) -> ResearchUnderstandingFeedbackListResponse:
    items = await run_in_threadpool(
        feedback_service.list_feedback,
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
        finding_id=finding_id,
        claim_id=claim_id,
    )
    return ResearchUnderstandingFeedbackListResponse(
        collection_id=collection_id,
        items=[_feedback_response(item) for item in items],
    )


def _feedback_response(
    feedback: ResearchUnderstandingFeedback,
) -> ResearchUnderstandingFeedbackResponse:
    return ResearchUnderstandingFeedbackResponse(**feedback.to_record())


@router.post(
    "/{collection_id}/research-understanding/curations",
    response_model=ResearchUnderstandingCurationResponse,
    summary="记录 research understanding finding 专家校正",
)
async def create_research_understanding_curation(
    collection_id: str,
    payload: ResearchUnderstandingCurationCreateRequest,
    request: Request,
) -> ResearchUnderstandingCurationResponse:
    curation = await run_in_threadpool(
        feedback_service.record_curation,
        collection_id=collection_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        finding_id=payload.finding_id,
        claim_id=payload.claim_id,
        curated_claim_type=payload.curated_claim_type,
        curated_status=payload.curated_status,
        curated_statement=payload.curated_statement,
        curated_support_grade=payload.curated_support_grade,
        curated_review_status=payload.curated_review_status,
        curated_variables=payload.curated_variables,
        curated_mediators=payload.curated_mediators,
        curated_outcomes=payload.curated_outcomes,
        curated_direction=payload.curated_direction,
        curated_scope_summary=payload.curated_scope_summary,
        curated_evidence_ref_ids=payload.curated_evidence_ref_ids,
        curated_context_ids=payload.curated_context_ids,
        note=payload.note,
        reviewer=_reviewer_for_write(request, payload.reviewer),
    )
    return _curation_response(curation)


@router.get(
    "/{collection_id}/research-understanding/curations",
    response_model=ResearchUnderstandingCurationListResponse,
    summary="读取 research understanding finding 专家校正",
)
async def list_research_understanding_curations(
    collection_id: str,
    scope_type: str | None = Query(default=None, max_length=32),
    scope_id: str | None = Query(default=None, max_length=160),
    finding_id: str | None = Query(default=None, max_length=200),
    claim_id: str | None = Query(default=None, max_length=200),
) -> ResearchUnderstandingCurationListResponse:
    items = await run_in_threadpool(
        feedback_service.list_curations,
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
        finding_id=finding_id,
        claim_id=claim_id,
    )
    return ResearchUnderstandingCurationListResponse(
        collection_id=collection_id,
        items=[_curation_response(item) for item in items],
    )


def _curation_response(
    curation: ResearchUnderstandingCuration,
) -> ResearchUnderstandingCurationResponse:
    return ResearchUnderstandingCurationResponse(**curation.to_record())


def _reviewer_for_write(request: Request, requested_reviewer: str | None) -> str:
    """Use session identity for human review, while preserving agent reviewers."""

    normalized_requested = (requested_reviewer or "").strip()
    if _is_agent_reviewer(normalized_requested):
        return normalized_requested
    user = require_current_user(request)
    return _current_user_reviewer(user)


def _is_agent_reviewer(reviewer: str) -> bool:
    normalized = reviewer.lower()
    return normalized.startswith("ai-reviewer") or normalized.startswith("agent-")


def _current_user_reviewer(user: dict[str, Any]) -> str:
    for key in ("email", "display_name", "user_id"):
        value = str(user.get(key) or "").strip()
        if value:
            return value
    raise ValueError("authenticated user has no reviewer identity")


@router.get(
    "/{collection_id}/research-understanding/gold-draft",
    response_model=ResearchUnderstandingGoldDraftResponse,
    summary="导出 research understanding 专家校正 gold 草稿",
)
async def export_research_understanding_gold_draft(
    collection_id: str,
    scope_type: str = Query(..., max_length=32),
    scope_id: str = Query(..., min_length=1, max_length=160),
) -> ResearchUnderstandingGoldDraftResponse:
    draft = await run_in_threadpool(
        feedback_service.export_gold_draft,
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    return ResearchUnderstandingGoldDraftResponse(**draft)


@router.get(
    "/{collection_id}/research-understanding/dataset",
    response_model=ResearchUnderstandingDatasetResponse,
    summary="导出 research understanding finding 数据集样本",
)
async def export_research_understanding_dataset(
    collection_id: str,
    scope_type: str = Query(..., max_length=32),
    scope_id: str = Query(..., min_length=1, max_length=160),
    label_status: ResearchUnderstandingDatasetLabelStatus | None = Query(default=None),
    dataset_use_status: ResearchUnderstandingDatasetUseStatus | None = Query(default=None),
    format: ResearchUnderstandingDatasetExportFormat = Query(default="json"),
) -> ResearchUnderstandingDatasetResponse | Response:
    dataset = await run_in_threadpool(
        feedback_service.export_dataset,
        collection_id=collection_id,
        scope_type=scope_type,
        scope_id=scope_id,
        label_status=label_status,
        dataset_use_status=dataset_use_status,
    )
    response = ResearchUnderstandingDatasetResponse(**dataset)
    if format == "jsonl":
        return _dataset_jsonl_response(response)
    if format == "messages_jsonl":
        return _dataset_jsonl_response(response, messages_only=True)
    if format == "training_jsonl":
        return _dataset_jsonl_response(
            response,
            messages_only=True,
            include_training_metadata=True,
        )
    if format == "review_jsonl":
        return _dataset_review_jsonl_response(response)
    if format == "decision_template":
        return _dataset_decision_template_response(response)
    if format == "agent_review_prompt_jsonl":
        return _dataset_agent_review_prompt_response(response)
    if format == "review_packet":
        return _dataset_review_packet_response(response)
    return response


@router.get(
    "/{collection_id}/research-understanding/dataset/collection",
    response_model=ResearchUnderstandingDatasetResponse,
    summary="导出 collection 级 research understanding finding 数据集样本",
)
async def export_collection_research_understanding_dataset(
    collection_id: str,
    scope_type: str = Query(default="goal", max_length=32),
    label_status: ResearchUnderstandingDatasetLabelStatus | None = Query(default=None),
    dataset_use_status: ResearchUnderstandingDatasetUseStatus | None = Query(default=None),
    format: ResearchUnderstandingDatasetExportFormat = Query(default="json"),
) -> ResearchUnderstandingDatasetResponse | Response:
    dataset = await run_in_threadpool(
        feedback_service.export_collection_dataset,
        collection_id=collection_id,
        scope_type=scope_type,
        label_status=label_status,
        dataset_use_status=dataset_use_status,
    )
    response = ResearchUnderstandingDatasetResponse(**dataset)
    if format == "jsonl":
        return _dataset_jsonl_response(response)
    if format == "messages_jsonl":
        return _dataset_jsonl_response(response, messages_only=True)
    if format == "training_jsonl":
        return _dataset_jsonl_response(
            response,
            messages_only=True,
            include_training_metadata=True,
        )
    if format == "review_jsonl":
        return _dataset_review_jsonl_response(response)
    if format == "decision_template":
        return _dataset_decision_template_response(response)
    if format == "agent_review_prompt_jsonl":
        return _dataset_agent_review_prompt_response(response)
    if format == "review_packet":
        return _dataset_review_packet_response(response)
    return response
