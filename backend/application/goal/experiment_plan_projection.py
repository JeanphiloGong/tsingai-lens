"""Boundary mapping for persisted experiment-plan revisions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from domain.goal import ExperimentPlanRecord, normalize_experiment_plan_status
from domain.goal.experiment_plan import _optional_text, _positive_int, _required_text, _string_mapping


def experiment_plan_from_record(payload: Mapping[str, Any]) -> ExperimentPlanRecord:
    source_links = payload.get("source_links")
    structured_plan = payload.get("structured_plan")
    return ExperimentPlanRecord(
        plan_id=_required_text(payload.get("plan_id"), "plan_id"),
        collection_id=_required_text(payload.get("collection_id"), "collection_id"),
        objective_id=_required_text(payload.get("objective_id"), "objective_id"),
        title=_required_text(payload.get("title"), "title"),
        content=_required_text(payload.get("content"), "content"),
        status=normalize_experiment_plan_status(payload.get("status")),
        source_message_id=_optional_text(payload.get("source_message_id")),
        source_links=tuple(_string_mapping(item) for item in source_links if isinstance(item, Mapping))
        if isinstance(source_links, (list, tuple)) else (),
        metadata=dict(payload.get("metadata")) if isinstance(payload.get("metadata"), Mapping) else {},
        created_by=_optional_text(payload.get("created_by")),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        plan_version=_positive_int(payload.get("plan_version", 1), "plan_version"),
        parent_plan_id=_optional_text(payload.get("parent_plan_id")),
        structured_plan=deepcopy(dict(structured_plan)) if isinstance(structured_plan, Mapping) else structured_plan,
        updated_by=_optional_text(payload.get("updated_by")),
    )


def experiment_plan_record(plan: ExperimentPlanRecord) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "collection_id": plan.collection_id,
        "objective_id": plan.objective_id,
        "title": plan.title,
        "content": plan.content,
        "status": plan.status,
        "source_message_id": plan.source_message_id,
        "source_links": [dict(link) for link in plan.source_links],
        "metadata": dict(plan.metadata),
        "created_by": plan.created_by,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "plan_version": plan.plan_version,
        "parent_plan_id": plan.parent_plan_id,
        "structured_plan": deepcopy(dict(plan.structured_plan)) if plan.structured_plan is not None else None,
        "updated_by": plan.updated_by,
    }
