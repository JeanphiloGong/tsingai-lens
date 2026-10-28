from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping


ExperimentPlanStatus = Literal["draft", "ready_for_review", "archived"]
EXPERIMENT_PLAN_STATUSES = {"draft", "ready_for_review", "archived"}


class ExperimentPlanRevisionConflictError(ValueError):
    """The requested parent already has a successor or was otherwise superseded."""


@dataclass(frozen=True)
class ExperimentPlanRecord:
    plan_id: str
    collection_id: str
    objective_id: str
    title: str
    content: str
    status: ExperimentPlanStatus
    source_message_id: str | None
    source_links: tuple[Mapping[str, str], ...]
    metadata: Mapping[str, Any]
    created_by: str | None
    created_at: str
    updated_at: str
    plan_version: int = 1
    parent_plan_id: str | None = None
    structured_plan: Mapping[str, Any] | None = None
    updated_by: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.plan_version, bool)
            or not isinstance(self.plan_version, int)
            or self.plan_version < 1
        ):
            raise ValueError("plan_version must be a positive integer")
        if self.plan_version == 1 and self.parent_plan_id is not None:
            raise ValueError("the first revision cannot have a parent_plan_id")
        if self.plan_version > 1 and self.parent_plan_id is None:
            raise ValueError("parent_plan_id is required after the first revision")
        if self.parent_plan_id == self.plan_id:
            raise ValueError("parent_plan_id cannot equal plan_id")
        if self.plan_version > 1 and self.updated_by is None:
            raise ValueError("updated_by is required after the first revision")
        if self.structured_plan is not None and not isinstance(
            self.structured_plan, Mapping
        ):
            raise ValueError("structured_plan must be an object")

    def with_updates(
        self,
        *,
        title: Any,
        content: Any,
        status: Any,
        updated_at: str,
    ) -> "ExperimentPlanRecord":
        return replace(
            self,
            title=_required_text(title, "title"),
            content=_required_text(content, "content"),
            status=normalize_experiment_plan_status(status),
            updated_at=str(updated_at),
        )

    def next_revision(
        self,
        *,
        plan_id: Any,
        title: Any,
        content: Any,
        status: Any,
        structured_plan: Mapping[str, Any] | None,
        updated_by: Any,
        updated_at: str,
        source_links: tuple[Mapping[str, str], ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ExperimentPlanRecord":
        return replace(
            self,
            plan_id=_required_text(plan_id, "plan_id"),
            title=_required_text(title, "title"),
            content=_required_text(content, "content"),
            status=normalize_experiment_plan_status(status),
            plan_version=self.plan_version + 1,
            parent_plan_id=self.plan_id,
            structured_plan=(
                deepcopy(dict(structured_plan))
                if isinstance(structured_plan, Mapping)
                else structured_plan
            ),
            updated_by=_optional_text(updated_by),
            updated_at=str(updated_at),
            source_links=tuple(
                _string_mapping(item)
                for item in (self.source_links if source_links is None else source_links)
            ),
            metadata=dict(self.metadata if metadata is None else metadata),
        )

def normalize_experiment_plan_status(value: Any) -> ExperimentPlanStatus:
    status = str(value or "draft").strip().lower()
    if status not in EXPERIMENT_PLAN_STATUSES:
        raise ValueError(
            "experiment plan status must be one of: draft, ready_for_review, archived"
        )
    return status  # type: ignore[return-value]


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _string_mapping(value: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(key): str(item)
        for key, item in value.items()
        if _optional_text(key) and _optional_text(item)
    }


__all__ = [
    "EXPERIMENT_PLAN_STATUSES",
    "ExperimentPlanRecord",
    "ExperimentPlanRevisionConflictError",
    "ExperimentPlanStatus",
    "normalize_experiment_plan_status",
]
