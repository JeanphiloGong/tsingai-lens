from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Mapping

from application.evaluation import finding_feedback_service
from application.goal.protocol_contract import (
    proposed_design_choices_are_source_independent,
    ved_design_is_scientifically_consistent,
)
from application.source import collection_service
from domain.goal import ExperimentPlanRecord, ExperimentPlanStatus
from exceptions import (
    RequestInvalidException,
    ResourceConflictException,
    ResourceNotFoundException,
)

_HISTORICAL_REVIEW_GATE = "reviewed_findings"


class ExperimentPlanNotFoundError(ResourceNotFoundException):
    def __init__(self, collection_id: str, objective_id: str, plan_id: str) -> None:
        self.collection_id = collection_id
        self.objective_id = objective_id
        self.plan_id = plan_id
        super().__init__(
            f"experiment plan not found: {plan_id}",
            data={
                "code": "experiment_plan_not_found",
                "collection_id": collection_id,
                "objective_id": objective_id,
                "plan_id": plan_id,
            },
        )


from repositories.experiment_plan_repository import ExperimentPlanRepo


async def create_plan(
    *,
    collection_id: str,
    objective_id: str,
    title: str,
    content: str,
    structured_plan: Mapping[str, Any] | None = None,
    created_by: str,
) -> ExperimentPlanRecord:
    await collection_service.get_collection_for_user(collection_id, created_by)
    now = _now_iso()
    plan = ExperimentPlanRecord(
        plan_id=_plan_id(
            collection_id,
            objective_id,
            title,
            content,
            now,
        ),
        collection_id=collection_id,
        objective_id=objective_id,
        title=title,
        content=content,
        status="draft",
        source_message_id=None,
        source_links=(),
        metadata={"source": "manual"},
        created_by=created_by,
        updated_by=created_by,
        structured_plan=deepcopy(structured_plan),
        created_at=now,
        updated_at=now,
    )
    return await ExperimentPlanRepo.upsert_plan(plan)


async def create_agent_plan(
    *,
    collection_id: str,
    objective_id: str,
    title: str,
    content: str,
    source_links: list[Mapping[str, Any]],
    source_findings: list[Mapping[str, Any]],
    structured_plan: Mapping[str, Any],
    created_by: str,
    created_by_tool_call_id: str,
) -> ExperimentPlanRecord:
    """Persist one approved plan draft against current Finding snapshots."""

    await collection_service.get_collection_for_user(collection_id, created_by)
    if not created_by.strip():
        raise RequestInvalidException(
            "research plan requires an authenticated creator",
            data={"code": "experiment_plan_invalid"},
        )
    if not created_by_tool_call_id.strip():
        raise RequestInvalidException(
            "research plan requires an approved tool call",
            data={"code": "experiment_plan_invalid"},
        )
    if not source_findings:
        raise RequestInvalidException(
            "research plan requires at least one source Finding",
            data={"code": "experiment_plan_invalid"},
        )
    if not source_links:
        raise RequestInvalidException(
            "research plan requires at least one Evidence link",
            data={"code": "experiment_plan_invalid"},
        )
    normalized_links = [_source_link(item) for item in source_links]
    labels = [item["label"] for item in normalized_links]
    missing_labels = [label for label in labels if label not in content]
    if missing_labels:
        raise RequestInvalidException(
            "research plan content is missing visible Evidence citations: "
            + ", ".join(missing_labels),
            data={"code": "experiment_plan_invalid"},
        )
    if not _has_protocol_draft_structure(content):
        raise RequestInvalidException(
            "research plan is not a complete structured draft",
            data={"code": "experiment_plan_invalid"},
        )
    validity, reasons = await finding_feedback_service.source_snapshot_validity(
        collection_id=collection_id,
        objective_id=objective_id,
        source_findings=source_findings,
    )
    if validity != "current":
        raise ResourceConflictException(
            "research plan sources are stale"
            + (f": {', '.join(reasons)}" if reasons else ""),
            data={"code": "research_plan_sources_stale"},
        )

    now = _now_iso()
    plan = ExperimentPlanRecord(
        plan_id=_plan_id(
            collection_id,
            objective_id,
            title,
            content,
            created_by_tool_call_id,
            now,
        ),
        collection_id=collection_id,
        objective_id=objective_id,
        title=title,
        content=content,
        status="draft",
        source_message_id=None,
        source_links=tuple(normalized_links),
        metadata={
            "source": "research_agent",
            "review_gate": _HISTORICAL_REVIEW_GATE,
            "source_findings": [dict(item) for item in source_findings],
            "created_by_tool_call_id": created_by_tool_call_id,
            "source_validity": "current",
            "source_validity_reasons": [],
        },
        created_by=created_by,
        updated_by=created_by,
        structured_plan=deepcopy(structured_plan),
        created_at=now,
        updated_at=now,
    )
    return await ExperimentPlanRepo.upsert_plan(plan)


async def list_plans(
    collection_id: str,
    objective_id: str,
    *,
    user_id: str,
) -> tuple[ExperimentPlanRecord, ...]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    plans = await ExperimentPlanRepo.list_plans(collection_id, objective_id)
    result: list[ExperimentPlanRecord] = []
    for plan in plans:
        result.append(
            await _with_source_validity(plan)
            if _is_source_grounded_plan(plan)
            else plan
        )
    return tuple(result)


async def read_plan(
    collection_id: str,
    objective_id: str,
    plan_id: str,
    *,
    user_id: str,
) -> ExperimentPlanRecord:
    await collection_service.get_collection_for_user(collection_id, user_id)
    plan = await ExperimentPlanRepo.read_plan(collection_id, objective_id, plan_id)
    if plan is None:
        raise ExperimentPlanNotFoundError(collection_id, objective_id, plan_id)
    return await _with_source_validity(plan) if _is_source_grounded_plan(plan) else plan


async def update_plan(
    *,
    collection_id: str,
    objective_id: str,
    plan_id: str,
    title: str | None = None,
    content: str | None = None,
    status: ExperimentPlanStatus | None = None,
    structured_plan: Mapping[str, Any] | None = None,
    updated_by: str,
    source_links: list[Mapping[str, Any]] | None = None,
    source_findings: list[Mapping[str, Any]] | None = None,
    updated_by_tool_call_id: str | None = None,
) -> ExperimentPlanRecord:
    await collection_service.get_collection_for_user(collection_id, updated_by)
    plan = await ExperimentPlanRepo.read_plan(collection_id, objective_id, plan_id)
    if plan is None:
        raise ExperimentPlanNotFoundError(collection_id, objective_id, plan_id)
    title = plan.title if title is None else title
    content = plan.content if content is None else content
    status = plan.status if status is None else status
    source_grounded = _is_source_grounded_plan(plan)
    replacing_basis = any(
        value is not None
        for value in (
            source_links,
            source_findings,
            updated_by_tool_call_id,
        )
    )
    next_links: tuple[Mapping[str, str], ...] | None = None
    next_metadata: Mapping[str, Any] | None = None
    if replacing_basis:
        if not source_links or not source_findings:
            raise RequestInvalidException(
                "research plan revision requires Evidence links and Finding snapshots",
                data={"code": "experiment_plan_invalid"},
            )
        if not str(updated_by_tool_call_id or "").strip():
            raise RequestInvalidException(
                "research plan revision requires an approved tool call",
                data={"code": "experiment_plan_invalid"},
            )
        normalized_links = tuple(_source_link(item) for item in source_links)
        missing_labels = [
            item["label"] for item in normalized_links if item["label"] not in content
        ]
        if missing_labels:
            raise RequestInvalidException(
                "research plan content is missing visible Evidence citations: "
                + ", ".join(missing_labels),
                data={"code": "experiment_plan_invalid"},
            )
        if not _has_protocol_draft_structure(content):
            raise RequestInvalidException(
                "research plan is not a complete structured draft",
                data={"code": "experiment_plan_invalid"},
            )
        validity, reasons = await finding_feedback_service.source_snapshot_validity(
            collection_id=collection_id,
            objective_id=objective_id,
            source_findings=source_findings,
        )
        if validity != "current":
            raise ResourceConflictException(
                "research plan sources are stale"
                + (f": {', '.join(reasons)}" if reasons else ""),
                data={"code": "research_plan_sources_stale"},
            )
        next_links = normalized_links
        next_metadata = {
            **dict(plan.metadata),
            "source": "research_agent",
            "review_gate": _HISTORICAL_REVIEW_GATE,
            "source_findings": [dict(item) for item in source_findings],
            "updated_by_tool_call_id": updated_by_tool_call_id,
            "source_validity": "current",
            "source_validity_reasons": [],
        }
        source_grounded = True
    elif source_grounded:
        _validate_source_grounded_plan_edit(plan, content)
        if status == "ready_for_review":
            checked = await _with_source_validity(plan)
            if checked.metadata.get("source_validity") != "current":
                raise ResourceConflictException(
                    "historical source Findings are stale",
                    data={"code": "research_plan_sources_stale"},
                )
    if not updated_by or not updated_by.strip():
        raise RequestInvalidException(
            "research plan revision requires an authenticated updater",
            data={"code": "experiment_plan_invalid"},
        )
    now = _now_iso()
    next_structure = (
        structured_plan if structured_plan is not None else plan.structured_plan
    )
    stored = await ExperimentPlanRepo.append_plan_revision(
        plan.next_revision(
            plan_id=_plan_id(
                plan.plan_id,
                plan.plan_version + 1,
                title,
                content,
                status,
                updated_by,
                now,
            ),
            title=title,
            content=content,
            status=status,
            structured_plan=next_structure,
            updated_by=updated_by,
            updated_at=now,
            source_links=next_links,
            metadata=next_metadata,
        )
    )
    return await _with_source_validity(stored) if source_grounded else stored


async def _with_source_validity(
    plan: ExperimentPlanRecord,
) -> ExperimentPlanRecord:
    if _is_historical_grounded_plan(plan) and (
        not proposed_design_choices_are_source_independent(plan.content)
        or not ved_design_is_scientifically_consistent(plan.content)
    ):
        validity, reasons = "stale", ["protocol_design_inconsistent"]
    else:
        source_findings = tuple(
            item
            for item in plan.metadata.get("source_findings", [])
            if isinstance(item, dict)
        )
        validity, reasons = await finding_feedback_service.source_snapshot_validity(
            collection_id=plan.collection_id,
            objective_id=plan.objective_id,
            source_findings=source_findings,
        )
    return replace(
        plan,
        metadata={
            **dict(plan.metadata),
            "source_validity": validity,
            "source_validity_reasons": reasons,
        },
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_id(*parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return "exp_" + sha1(payload.encode("utf-8")).hexdigest()[:16]


def _is_historical_grounded_plan(plan: ExperimentPlanRecord) -> bool:
    return plan.metadata.get("source") != "research_agent" and (
        bool(plan.source_message_id)
        or plan.metadata.get("source") == "goal_copilot"
        or plan.metadata.get("review_gate") == _HISTORICAL_REVIEW_GATE
    )


def _is_source_grounded_plan(plan: ExperimentPlanRecord) -> bool:
    return plan.metadata.get(
        "source"
    ) == "research_agent" or _is_historical_grounded_plan(plan)


def _validate_source_grounded_plan_edit(
    plan: ExperimentPlanRecord,
    content: str,
) -> None:
    if not _has_protocol_draft_structure(content):
        raise RequestInvalidException(
            "source-grounded plan is not a structured protocol draft",
            data={"code": "experiment_plan_invalid"},
        )
    if _is_historical_grounded_plan(plan):
        if not proposed_design_choices_are_source_independent(content):
            raise RequestInvalidException(
                "Proposed design choice contains an unattributed numeric or named detail",
                data={"code": "experiment_plan_invalid"},
            )
        if not ved_design_is_scientifically_consistent(content):
            raise RequestInvalidException(
                "VED design violates the constituent-state or causal-boundary contract",
                data={"code": "experiment_plan_invalid"},
            )
    visible_labels = [
        label
        for link in plan.source_links
        if (label := str(link.get("label") or "").strip())
    ]
    if plan.metadata.get("source") == "research_agent":
        if any(label not in content for label in visible_labels):
            raise RequestInvalidException(
                "research plan does not cite every visible Evidence label",
                data={"code": "experiment_plan_invalid"},
            )
    elif visible_labels and not any(label in content for label in visible_labels):
        raise RequestInvalidException(
            "historical grounded plan does not cite a visible source label",
            data={"code": "experiment_plan_invalid"},
        )


def _source_link(value: Mapping[str, Any]) -> dict[str, str]:
    kind = str(value.get("kind") or "").strip()
    label = str(value.get("label") or "").strip()
    href = str(value.get("href") or "").strip()
    if kind != "evidence" or not label or not href:
        raise RequestInvalidException(
            "research plan source links require Evidence kind, label, and href",
            data={"code": "experiment_plan_invalid"},
        )
    return {"kind": kind, "label": label, "href": href}


def _has_protocol_draft_structure(content: str) -> bool:
    normalized = content.lower()
    required_terms = (
        ("hypothesis", "假设"),
        ("variable matrix", "变量矩阵", "变量"),
        ("measurement", "measurements", "表征", "测试指标", "测量"),
        ("control", "controls", "对照"),
        ("risk", "risks", "limit", "limits", "风险", "限制"),
    )
    return all(any(term in normalized for term in terms) for terms in required_terms)


__all__ = [
    "ExperimentPlanNotFoundError",
    "create_plan",
    "create_agent_plan",
    "list_plans",
    "read_plan",
    "update_plan",
]
