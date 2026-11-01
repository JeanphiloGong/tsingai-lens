"""Parse and apply external human Finding review decisions."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Mapping,
)

from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    FINDING_ASSERTION_STRENGTHS,
    FINDING_ORIGINS,
    FINDING_SYNTHESIS_STATUSES,
    PAPER_CONTRIBUTION_STATUSES,
    Finding,
    FindingMechanismRelation,
    FindingPaperContribution,
)
from domain.core.scientific_fact import (
    SCIENTIFIC_CONTEXT_SCOPES,
    SCIENTIFIC_RESULT_DIRECTIONS,
    ScientificAttribute,
    ScientificContext,
)
from exceptions import (
    RequestInvalidException,
    ResourceConflictException,
    ResourceNotFoundException,
)


_ACTIONS = frozenset({"accept", "reject", "correct", "skip"})
_ISSUES = frozenset(
    {
        "evidence_not_grounded",
        "missing_evidence",
        "insufficient_evidence",
        "wrong_factor",
        "wrong_outcome",
        "wrong_direction",
        "wrong_context",
        "wrong_mechanism",
        "wrong_attribution",
        "wrong_synthesis",
        "overclaim",
        "unclear_statement",
        "other",
    }
)


from application.evaluation import finding_dataset_service
from application.evaluation import finding_feedback_service


async def import_rows(
    *,
    rows: list[dict[str, Any]],
    reviewer: str,
    user_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    reviewer = _human_reviewer(reviewer)
    validated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line_number, row in enumerate(rows, start=1):
        try:
            validated.append(
                await _decision(row, line_number=line_number, user_id=user_id)
            )
        except (
            ValueError,
            RequestInvalidException,
            ResourceConflictException,
            ResourceNotFoundException,
        ) as exc:
            errors.append({"line": line_number, "message": str(exc)})
    if errors:
        return _summary(
            status="fail",
            dry_run=dry_run,
            decisions=validated,
            errors=errors,
            written_count=0,
        )

    written_count = 0
    if not dry_run:
        for decision in validated:
            action = decision["action"]
            if action == "skip":
                continue
            payload = dict(decision["payload"])
            if action == "correct":
                await finding_feedback_service.record_curation(
                    reviewer=reviewer,
                    user_id=user_id,
                    **payload,
                )
            else:
                await finding_feedback_service.record_feedback(
                    reviewer=reviewer,
                    user_id=user_id,
                    **payload,
                )
            written_count += 1
    return _summary(
        status="pass",
        dry_run=dry_run,
        decisions=validated,
        errors=[],
        written_count=written_count,
    )


async def import_jsonl_file(
    *,
    input_path: Path,
    reviewer: str,
    user_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    return await import_rows(
        rows=read_review_jsonl(input_path),
        reviewer=reviewer,
        user_id=user_id,
        dry_run=dry_run,
    )


async def _decision(
    row: dict[str, Any],
    *,
    line_number: int,
    user_id: str,
) -> dict[str, Any]:
    if "expert_action" in row or "expert_note" in row:
        raise ValueError("expert_action and expert_note are not review JSONL fields")
    action = row.get("action")
    if not isinstance(action, str):
        raise ValueError("action must be accept, reject, correct, or skip")
    action = action.strip().lower()
    if action not in _ACTIONS:
        raise ValueError("action must be accept, reject, correct, or skip")
    identity = _identity(row)
    if action == "skip":
        return {"line": line_number, "action": action, "payload": identity}
    note = row.get("note")
    if note is not None:
        if not isinstance(note, str):
            raise ValueError("note must be text")
        note = note.strip() or None

    if action == "accept":
        await _require_dataset_item(identity, user_id=user_id)
        return {
            "line": line_number,
            "action": action,
            "payload": {
                **identity,
                "review_status": "correct",
                "issue_type": "none",
                "note": note,
            },
        }
    if action == "reject":
        await _require_dataset_item(identity, user_id=user_id)
        issue_type = row.get("issue_type")
        if not isinstance(issue_type, str):
            raise ValueError("reject requires a valid issue_type")
        issue_type = issue_type.strip().lower()
        if issue_type not in _ISSUES:
            raise ValueError("reject requires a valid issue_type")
        return {
            "line": line_number,
            "action": action,
            "payload": {
                **identity,
                "review_status": "incorrect",
                "issue_type": issue_type,
                "note": note,
            },
        }

    curated_finding = row.get("curated_finding")
    if not isinstance(curated_finding, dict):
        raise ValueError("correct requires one complete curated_finding")
    candidate = parse_curated_finding(curated_finding)
    await finding_feedback_service.validate_curation(
        **identity,
        curated_finding=candidate,
        user_id=user_id,
    )
    curated_status = row.get("curated_status", "limited")
    if not isinstance(curated_status, str):
        raise ValueError("curated_status must be text")
    curated_status = curated_status.strip() or "limited"
    if curated_status not in {"supported", "limited", "conflicted", "unsupported"}:
        raise ValueError("correct requires a valid curated_status")
    return {
        "line": line_number,
        "action": action,
        "payload": {
            **identity,
            "curated_status": curated_status,
            "curated_finding": candidate,
            "note": note,
        },
    }


async def _require_dataset_item(
    identity: dict[str, Any],
    *,
    user_id: str,
) -> dict[str, Any]:
    dataset = await finding_dataset_service.export_dataset(
        collection_id=identity["collection_id"],
        objective_id=identity["objective_id"],
        user_id=user_id,
    )
    for item in dataset.get("items", []):
        if (
            item.get("analysis_version") == identity["analysis_version"]
            and item.get("finding_id") == identity["finding_id"]
        ):
            return item
    raise ValueError("Finding version is not present in the current dataset")


def read_review_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number} must be a JSON object")
            rows.append(payload)
    return rows


def _identity(row: dict[str, Any]) -> dict[str, Any]:
    if "claim_id" in row:
        raise ValueError("claim_id is not part of the Finding review contract")
    for name in ("collection_id", "objective_id", "finding_id"):
        if not isinstance(row.get(name), str) or not row[name].strip():
            raise ValueError(f"{name} is required and must be text")
    collection_id = row["collection_id"].strip()
    objective_id = row["objective_id"].strip()
    finding_id = row["finding_id"].strip()
    version = row.get("analysis_version")
    if type(version) not in (int, str):
        raise ValueError("analysis_version must be a positive integer")
    try:
        analysis_version = int(version)
    except (TypeError, ValueError):
        raise ValueError("analysis_version must be a positive integer") from None
    if not collection_id or not objective_id or analysis_version < 1 or not finding_id:
        raise ValueError(
            "collection_id, objective_id, analysis_version, and finding_id are required"
        )
    return {
        "collection_id": collection_id,
        "objective_id": objective_id,
        "analysis_version": analysis_version,
        "finding_id": finding_id,
    }


def _human_reviewer(value: str) -> str:
    reviewer = value.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    normalized = reviewer.lower()
    if normalized.startswith("ai-reviewer") or normalized.startswith("agent-"):
        raise ValueError("reviewer must be a human expert id")
    return reviewer


def _summary(
    *,
    status: str,
    dry_run: bool,
    decisions: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    written_count: int,
) -> dict[str, Any]:
    counts = {action: 0 for action in sorted(_ACTIONS)}
    for decision in decisions:
        counts[decision["action"]] += 1
    return {
        "status": status,
        "dry_run": dry_run,
        "total_rows": len(decisions) + len(errors),
        "written_count": written_count,
        "skipped_count": counts["skip"],
        "counts": counts,
        "errors": errors,
        "warnings": [],
    }


def parse_curated_finding(payload: Mapping[str, Any]) -> Finding:
    """Reject malformed external review JSON, then construct the Finding once."""
    required = {
        "collection_id",
        "objective_id",
        "analysis_version",
        "finding_id",
        "statement",
        "factors",
        "outcome",
        "direction",
        "assertion_strength",
        "attribution_scope",
        "synthesis_status",
        "certainty",
        "display_rank",
        "mechanisms",
        "scientific_context",
        "limitations",
        "paper_contributions",
        "origin",
        "source_analysis_version",
        "parent_finding_id",
        "created_by_user_id",
        "created_by_tool_call_id",
        "created_at",
    }
    optional = {"selection_ids", "comparison_group_ids", "warnings"}
    error = "curated_finding must use the complete canonical Finding contract"
    if (
        not isinstance(payload, Mapping)
        or not required <= payload.keys()
        or payload.keys() - required - optional
    ):
        raise ValueError(error)
    for name in ("collection_id", "objective_id", "finding_id", "statement", "outcome"):
        if (
            not isinstance(payload[name], str)
            or not payload[name]
            or payload[name] != payload[name].strip()
        ):
            raise ValueError(f"{error}: invalid {name}")
    for name in ("parent_finding_id", "created_by_user_id", "created_by_tool_call_id"):
        value = payload[name]
        if value is not None and (
            not isinstance(value, str) or not value or value != value.strip()
        ):
            raise ValueError(f"{error}: invalid {name}")
    for name, allowed in (
        ("direction", SCIENTIFIC_RESULT_DIRECTIONS),
        ("assertion_strength", FINDING_ASSERTION_STRENGTHS),
        ("attribution_scope", EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"}),
        ("synthesis_status", FINDING_SYNTHESIS_STATUSES),
        ("origin", FINDING_ORIGINS),
    ):
        if not isinstance(payload[name], str) or payload[name] not in allowed:
            raise ValueError(f"{error}: invalid {name}")
    for name, minimum in (
        ("analysis_version", 1),
        ("display_rank", 0),
        ("source_analysis_version", 1),
    ):
        value = payload[name]
        if name == "source_analysis_version" and value is None:
            continue
        if type(value) is not int or value < minimum:
            raise ValueError(f"{error}: invalid {name}")
    if (
        type(payload["certainty"]) not in (int, float)
        or not 0 <= payload["certainty"] <= 1
    ):
        raise ValueError(f"{error}: invalid certainty")
    for name in (
        "factors",
        "limitations",
        "selection_ids",
        "comparison_group_ids",
        "warnings",
    ):
        values = payload.get(name, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value or value != value.strip()
            for value in values
        ):
            raise ValueError(f"{error}: invalid {name}")
    if not isinstance(payload["mechanisms"], list) or not isinstance(
        payload["paper_contributions"], list
    ):
        raise ValueError(f"{error}: mechanisms and paper_contributions must be lists")
    mechanisms = []
    for item in payload["mechanisms"]:
        if not isinstance(item, Mapping) or item.keys() != {
            "source_term",
            "relation_type",
            "target_term",
            "direction",
            "assertion_strength",
            "supporting_evidence_ids",
        }:
            raise ValueError(f"{error}: invalid mechanism fields")
        for name in ("source_term", "relation_type", "target_term"):
            if (
                not isinstance(item[name], str)
                or not item[name]
                or item[name] != item[name].strip()
            ):
                raise ValueError(f"{error}: invalid mechanism {name}")
        if item["direction"] is not None and (
            not isinstance(item["direction"], str)
            or item["direction"] not in SCIENTIFIC_RESULT_DIRECTIONS
        ):
            raise ValueError(f"{error}: invalid mechanism direction")
        if (
            not isinstance(item["assertion_strength"], str)
            or item["assertion_strength"] not in FINDING_ASSERTION_STRENGTHS
        ):
            raise ValueError(f"{error}: invalid mechanism assertion_strength")
        refs = item["supporting_evidence_ids"]
        if not isinstance(refs, list) or any(
            not isinstance(ref, str) or not ref or ref != ref.strip() for ref in refs
        ):
            raise ValueError(f"{error}: invalid mechanism evidence")
        mechanisms.append(
            FindingMechanismRelation(
                source_term=item["source_term"],
                relation_type=item["relation_type"],
                target_term=item["target_term"],
                direction=item["direction"],
                assertion_strength=item["assertion_strength"],
                supporting_evidence_ids=tuple(refs),
            )
        )
    contributions = []
    evidence_fields = (
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "context_evidence_ids",
        "condition_boundary_evidence_ids",
    )
    for item in payload["paper_contributions"]:
        if not isinstance(item, Mapping) or item.keys() != {
            "document_id",
            "analysis_status",
            *evidence_fields,
        }:
            raise ValueError(f"{error}: invalid paper contribution fields")
        if (
            not isinstance(item["document_id"], str)
            or not item["document_id"]
            or item["document_id"] != item["document_id"].strip()
        ):
            raise ValueError(f"{error}: invalid contribution document_id")
        if (
            not isinstance(item["analysis_status"], str)
            or item["analysis_status"] not in PAPER_CONTRIBUTION_STATUSES
        ):
            raise ValueError(f"{error}: invalid contribution analysis_status")
        for name in evidence_fields:
            refs = item[name]
            if not isinstance(refs, list) or any(
                not isinstance(ref, str) or not ref or ref != ref.strip()
                for ref in refs
            ):
                raise ValueError(f"{error}: invalid {name}")
        contributions.append(
            FindingPaperContribution(
                document_id=item["document_id"],
                analysis_status=item["analysis_status"],
                supporting_evidence_ids=tuple(item["supporting_evidence_ids"]),
                contradicting_evidence_ids=tuple(item["contradicting_evidence_ids"]),
                context_evidence_ids=tuple(item["context_evidence_ids"]),
                condition_boundary_evidence_ids=tuple(
                    item["condition_boundary_evidence_ids"]
                ),
            )
        )
    context = payload["scientific_context"]
    if not isinstance(context, Mapping) or context.keys() != {
        "material",
        "sample",
        "process",
        "test",
    }:
        raise ValueError(f"{error}: invalid scientific_context")
    context_values = {}
    for name in ("material", "sample", "process", "test"):
        if not isinstance(context[name], list):
            raise ValueError(f"{error}: {name} must be a list")
        attributes = []
        for item in context[name]:
            if (
                not isinstance(item, Mapping)
                or not {"name", "value", "unit"} <= item.keys()
                or item.keys()
                - {"name", "value", "unit", "context_scope", "applies_to_outcomes"}
            ):
                raise ValueError(f"{error}: invalid scientific attribute fields")
            if (
                not isinstance(item["name"], str)
                or not item["name"].strip()
                or type(item["value"]) not in (str, int, float, bool)
            ):
                raise ValueError(f"{error}: invalid scientific attribute")
            if isinstance(item["value"], float) and not math.isfinite(item["value"]):
                raise ValueError(f"{error}: invalid scientific value")
            if item["unit"] is not None and not isinstance(item["unit"], str):
                raise ValueError(f"{error}: invalid scientific unit")
            if (
                not isinstance(item.get("context_scope", "unknown"), str)
                or item.get("context_scope", "unknown") not in SCIENTIFIC_CONTEXT_SCOPES
            ):
                raise ValueError(f"{error}: invalid scientific context_scope")
            outcomes = item.get("applies_to_outcomes", [])
            if not isinstance(outcomes, list) or any(
                not isinstance(value, str) for value in outcomes
            ):
                raise ValueError(f"{error}: invalid applies_to_outcomes")
            attributes.append(
                ScientificAttribute(
                    name=item["name"],
                    value=item["value"],
                    unit=item["unit"],
                    context_scope=item.get("context_scope", "unknown"),
                    applies_to_outcomes=tuple(outcomes),
                )
            )
        context_values[name] = tuple(attributes)
    created_at = payload["created_at"]
    if created_at is not None:
        if not isinstance(created_at, str):
            raise ValueError(f"{error}: invalid created_at")
        created_at = datetime.fromisoformat(created_at)
    return Finding(
        collection_id=payload["collection_id"],
        objective_id=payload["objective_id"],
        analysis_version=payload["analysis_version"],
        finding_id=payload["finding_id"],
        statement=payload["statement"],
        factors=tuple(payload["factors"]),
        outcome=payload["outcome"],
        direction=payload["direction"],
        assertion_strength=payload["assertion_strength"],
        attribution_scope=payload["attribution_scope"],
        synthesis_status=payload["synthesis_status"],
        certainty=payload["certainty"],
        display_rank=payload["display_rank"],
        mechanisms=tuple(mechanisms),
        scientific_context=ScientificContext(**context_values),
        limitations=tuple(payload["limitations"]),
        paper_contributions=tuple(contributions),
        origin=payload["origin"],
        source_analysis_version=payload["source_analysis_version"],
        parent_finding_id=payload["parent_finding_id"],
        created_by_user_id=payload["created_by_user_id"],
        created_by_tool_call_id=payload["created_by_tool_call_id"],
        created_at=created_at,
        warnings=tuple(payload.get("warnings", [])),
        selection_ids=tuple(payload.get("selection_ids", [])),
        comparison_group_ids=tuple(payload.get("comparison_group_ids", [])),
    )
